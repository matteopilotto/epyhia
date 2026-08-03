import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.models.actions import Action

router = APIRouter(dependencies=[Depends(require_operator)])


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
