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
    """Put a `failed` stage back on the queue (T142, FR-044).

    `failed` is terminal by design — `sweep_expired_leases` reclaims lapsed leases and
    deliberately does not touch it, because auto-retrying a handler exception is the loop the
    attempts cap exists to prevent. What was missing is the affordance to leave it, and a
    human clicking a button is the circuit breaker that cap stands in for, which is why
    `attempts` resets to 0 rather than carrying its history forward.

    Repeating no effect is what makes this safe: every gate key derives from the brief hash
    (§7.2), so a re-queued stage's `gate.request` short-circuits onto the rows that already
    succeeded and returns their stored evidence. A re-queued `site` whose deploy already
    succeeded republishes nothing.

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

    # Only `failed`. A `running` task belongs to the lease sweep and an `awaiting_approval`
    # one belongs to the approve button; this is the route out of the single state that
    # nothing else can leave.
    if task.state != "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "not_failed",
                "state": task.state,
                "detail": f"only a failed task can be re-queued; this one is {task.state}",
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
    await session.commit()
    return {"state": "pending"}
