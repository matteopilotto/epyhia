import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import settings
from epyhia.models.actions import Action
from epyhia.models.agent_calls import AgentCall
from epyhia.models.runs import Run

HALTED = "halted_budget"


class BudgetNotConfigured(Exception):
    """`RUN_BUDGET_USD` is absent or unreadable.

    Raised at the seam that needs the number, never at import or at start-up: the app must
    start with nothing configured and fail only where the missing value is actually used,
    with a sentence rather than a stack trace (FR-064, SC-010).
    """

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(f"budget not configured: {variable}")


def _amount(raw: str | None, variable: str) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise BudgetNotConfigured(variable) from exc


def configured_run_budget() -> Decimal:
    """The ceiling a new run opens against. Every run needs one — `runs.budget_usd` is NOT
    NULL — so an absent value is a refusal to open the run, not a default."""
    budget = _amount(settings.run_budget_usd, "RUN_BUDGET_USD")
    if budget is None:
        raise BudgetNotConfigured("RUN_BUDGET_USD")
    return budget


async def spend_for(session: AsyncSession, run_id: uuid.UUID) -> Decimal:
    """What the run has cost so far: model spend plus gate-action spend, as **one** number
    (§4.2, FR-052).

    Two counters against two budgets would remove the thing that makes `ANTHROPIC_API_KEY`
    sitting outside the gate defensible — inference is metered rather than gated precisely
    because it rolls up against the same ceiling as everything the gate does.

    Neither sum re-derives a cost. `agent_calls.cost_usd` is NOT NULL because `ledger` raised
    on an unknown model before the row could exist, so nothing is coalesced there. A NULL
    `actions.cost_usd` is a different statement: the provider billed nothing for that action,
    which is what a Vercel deploy and a test-mode Stripe call actually cost.
    """
    model_spend = await session.scalar(
        select(func.coalesce(func.sum(AgentCall.cost_usd), 0)).where(AgentCall.run_id == run_id)
    )
    action_spend = await session.scalar(
        select(func.coalesce(func.sum(Action.cost_usd), 0)).where(Action.run_id == run_id)
    )
    return Decimal(model_spend) + Decimal(action_spend)


async def enforce_run_budget(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Roll the run's spend up onto its row and halt it if it has crossed its budget.

    Returns whether the run is halted. A halted run stops *starting* new work; it abandons
    nothing already in flight. An action mid-execution is still driven to a `verify()` probe
    and still needs evidence to reach `succeeded`, and an `awaiting_approval` row is left
    exactly where it is (FR-053, contracts/action-gate.md §4).
    """
    run = await session.get(Run, run_id)
    run.spend_usd = await spend_for(session, run_id)
    if run.status == "running" and run.spend_usd >= Decimal(run.budget_usd):
        run.status = HALTED
    await session.commit()
    return run.status == HALTED
