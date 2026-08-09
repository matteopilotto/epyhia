import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.cost.budget import spend_for
from epyhia.models.agent_calls import AgentCall
from epyhia.models.runs import Run

router = APIRouter(dependencies=[Depends(require_operator)])


def _serialize(call: AgentCall) -> dict:
    return {
        "id": call.id,
        "agent": call.agent,
        "model_id": call.model_id,
        "tier": call.tier,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cache_write_tokens": call.cache_write_tokens,
        "cache_read_tokens": call.cache_read_tokens,
        "cost_usd": call.cost_usd,
        "latency_ms": call.latency_ms,
        "cache_hit": call.cache_hit,
        "created_at": call.created_at,
    }


@router.get("/runs/{run_id}/cost")
async def run_cost(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Every model call itemised, and **one** total against one budget (FR-052, §4.2).

    `total_usd` covers model spend and gate-action spend together, so it is deliberately not
    the sum of the listed calls — an action's cost is in the total without being a row here,
    and the run's `actions` are itemised by `GET /runs/{id}/actions`. Splitting the total in
    two would make the budget half-blind, which is the thing FR-052 exists to prevent.

    It is summed from the rows on read rather than echoing `runs.spend_usd`: that column is
    the enforcement roll-up, written when the worker next decides whether to keep going, so
    a run parked at an approval would otherwise report a number one stage out of date.
    """
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "run not found"}
        )

    calls = (
        await session.execute(
            select(AgentCall).where(AgentCall.run_id == run_id).order_by(AgentCall.created_at)
        )
    ).scalars().all()

    return {
        "run_id": run.id,
        "status": run.status,
        "budget_usd": run.budget_usd,
        "total_usd": await spend_for(session, run_id),
        "calls": [_serialize(call) for call in calls],
    }
