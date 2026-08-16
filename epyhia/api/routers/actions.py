import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.gate import gate
from epyhia.models.actions import Action
from epyhia.models.tasks import Task

router = APIRouter(dependencies=[Depends(require_operator)])


async def _enqueue_resume(session: AsyncSession, action: Action) -> None:
    """The decision is recorded here; the work happens in a worker (R7 step 5). No process
    held state across the human's pause, so the resume carries only the action id and the
    gate rebuilds everything else from the row."""
    session.add(
        Task(
            id=uuid.uuid4(),
            run_id=action.run_id,
            kind="resume",
            state="pending",
            payload={"action_id": str(action.id)},
        )
    )
    await session.commit()


def _serialize(action: Action) -> dict:
    return {
        "id": action.id,
        "action_type": action.action_type,
        "state": action.state,
        "requested_by": action.requested_by,
        # Showing the key is the cheapest way to make idempotency legible: on a re-run the
        # same key appears and the action short-circuits (§4.4, FR-039).
        "idempotency_key": action.idempotency_key,
        "request": action.request,
        "projected_cost_usd": action.projected_cost_usd,
        "cost_usd": action.cost_usd,
        "approval_decision": action.approval_decision,
        "approved_by": action.approved_by,
        "approved_at": action.approved_at,
        # The evidence the probe stored. This is what makes "deployed" non-self-reportable
        # anywhere in the system (FR-040, SC-002).
        "evidence": action.evidence,
        "error": action.error,
        "verify_attempts": action.verify_attempts,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


@router.get("/runs/{run_id}/actions")
async def list_run_actions(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    result = await session.execute(
        select(Action).where(Action.run_id == run_id).order_by(Action.created_at)
    )
    return [_serialize(action) for action in result.scalars().all()]


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: uuid.UUID,
    claims: dict = Depends(require_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Idempotent by construction: the decision is a transition on a keyed row, so a
    double-click, a reload, or a click after a redeploy all resolve to the same single
    execution — the second one 409s (FR-038)."""
    result = await gate.record_approval(session, action_id, claims["sub"])
    action = await session.get(Action, action_id)
    await _enqueue_resume(session, action)
    return {"state": result["state"], "approval_decision": "approved"}


@router.post("/actions/{action_id}/reverify")
async def reverify_action(
    action_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    """Re-open verification on an action that failed at verify (T146, FR-041's remedy).

    T142/T145's shape one layer down: `failed` is deliberately terminal at the gate —
    `request()` refuses it and `resume()` returns it untouched — and this is the operator
    affordance out of it. Verification only, never re-execution: the enqueued `resume` finds
    the row `verifying` and skips `execute()` by construction, so a re-verified `publish`
    probes the permalink the sink already holds rather than writing a duplicate post (§7.2).

    Refused unless `execute()`'s result is on the row — a failure at `execute()` (nothing in
    the world) or a pre-`actions.result` row with nothing recorded has nothing to prove, and
    re-opening it would burn five attempts to say `failed` again with a different error.

    The `resume` task's `_settle` then flips the original stage `done`/`failed` off the
    probe's verdict, which is what keeps a healed action from leaving its task lying.
    """
    action = await session.get(Action, action_id)
    if action is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "action not found"}
        )
    if action.state != "failed" or action.result is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "not_reverifiable",
                "state": action.state,
                "detail": (
                    "only a failed action whose execute() result is recorded can be "
                    "re-verified; this one is "
                    + (action.state if action.state != "failed" else "missing its result")
                ),
            },
        )
    action.state = "verifying"
    action.verify_attempts = 0
    action.error = None
    await session.commit()
    await _enqueue_resume(session, action)
    return {"state": "verifying"}


@router.post("/actions/{action_id}/deny")
async def deny_action(
    action_id: uuid.UUID,
    claims: dict = Depends(require_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Deny is terminal: nothing executes, ever, for that key (§6)."""
    result = await gate.deny(session, action_id, claims["sub"])
    action = await session.get(Action, action_id)
    # Still resumed, so the task parked at the pause learns the decision and settles rather
    # than waiting for an approval that will never come.
    await _enqueue_resume(session, action)
    return {"state": result["state"], "approval_decision": "denied"}
