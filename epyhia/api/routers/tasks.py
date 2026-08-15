import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.cost.budget import HALTED
from epyhia.models.runs import Run
from epyhia.models.tasks import Task

router = APIRouter(dependencies=[Depends(require_operator)])


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    """Put a `failed` or `done` stage back on the queue (T142, T145, FR-044).

    `failed` is terminal by design — `sweep_expired_leases` reclaims lapsed leases and
    deliberately does not touch it, because auto-retrying a handler exception is the loop the
    attempts cap exists to prevent. What was missing is the affordance to leave it, and a
    human clicking a button is the circuit breaker that cap stands in for, which is why
    `attempts` resets to 0 rather than carrying its history forward.

    `done` is equally terminal, and the operator remedy for a flagged artifact — correct the
    brand doc and re-run the stage that produced it — needs a route back into a stage that
    *completed* around its held output. Run `9445c473` proved the remedy unexecutable without
    one: its copy stage ended `done` with the artifact flagged, and the only way to re-run it
    was a raw UPDATE in psql (T145).

    Repeating no effect is what makes both safe: every gate key derives from the brief hash
    (§7.2), so a re-queued stage's `gate.request` short-circuits onto the rows that already
    succeeded and returns their stored evidence. A re-queued `site` whose deploy already
    succeeded republishes nothing. And agent calls memoise on the brand doc version (§7.3),
    so a re-run without an edit replays its stored outputs, while a re-run after one — the
    remedy case — regenerates precisely because the input that matters changed.

    Dependents need no handling either — `_CLAIM_SQL` already refuses to claim a task whose
    `depends_on` are not all `done`, so re-queueing an upstream stage leaves the ones below
    it blocked until it finishes and then lets them through.

    The audit trail is the `task` event the SSE timeline emits on every state transition, so
    the re-queue is visible without a new column.
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "task not found"}
        )

    # Only the terminal states. A `running` task belongs to the lease sweep, a `pending` one
    # to the claim loop, and an `awaiting_approval` one to the approve button; this is the
    # route out of the two states nothing else can leave.
    if task.state not in ("failed", "done"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "not_retryable",
                "state": task.state,
                "detail": (
                    "only a failed or done task can be re-queued; "
                    f"this one is {task.state}"
                ),
            },
        )

    # `enforce_run_budget` fails a claimed task immediately while the run is halted, so
    # without this the click would produce a task that goes pending → failed in under a
    # second carrying a different error than the one the operator was looking at.
    run = await session.get(Run, task.run_id)
    if run.status == HALTED:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "run_halted",
                "detail": "the run is halted on budget; re-queueing would fail on claim",
            },
        )

    await session.execute(
        text(
            "UPDATE tasks SET state = 'pending', error = NULL, lease_expires_at = NULL, "
            "attempts = 0 WHERE id = :id"
        ),
        {"id": task_id},
    )
    # A settled run re-opens with its stage: `succeeded`/`failed` are written where the
    # queue settles a task (T144), and re-queueing one is the operator's statement that the
    # run is not finished after all. `halted_budget` was refused above and stays put.
    if run.status in ("succeeded", "failed"):
        run.status = "running"
    await session.commit()
    return {"state": "pending"}
