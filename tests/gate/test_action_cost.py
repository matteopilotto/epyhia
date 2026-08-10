import uuid
from decimal import Decimal

import pytest
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.cost.budget import spend_for
from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action


async def _row(session: AsyncSession, key: str) -> Action:
    return (
        await session.execute(select(Action).where(Action.idempotency_key == key))
    ).scalar_one()


async def test_an_action_awaiting_approval_already_carries_its_projected_cost(
    gate_session: AsyncSession, fresh_session: AsyncSession
) -> None:
    """FR-039: the approval screen shows the projected cost. It cannot, if the number is
    only written after the operator has already decided."""
    registry.register(
        FakeAdapter("costed_approval", requires_approval=True, cost_usd=Decimal("2.50"))
    )
    key = str(uuid.uuid4())

    with pytest.raises(ApprovalRequired):
        await gate.request(
            gate_session,
            run_id=uuid.uuid4(),
            requested_by="ops",
            action_type="costed_approval",
            action_request={},
            idempotency_key=key,
        )

    row = await _row(fresh_session, key)
    assert row.state == "awaiting_approval"
    assert row.projected_cost_usd == Decimal("2.50")
    # Not yet actual: nothing has happened in the world, so nothing has been spent.
    assert row.cost_usd is None


async def test_a_succeeded_action_carries_an_actual_cost(
    gate_session: AsyncSession,
) -> None:
    """FR-050, and the assertion T123 makes of every action in the run."""
    registry.register(FakeAdapter("costed", cost_usd=Decimal("0")))
    key = str(uuid.uuid4())

    result = await gate.request(
        gate_session,
        run_id=uuid.uuid4(),
        requested_by="ops",
        action_type="costed",
        action_request={},
        idempotency_key=key,
    )
    assert result["state"] == "succeeded"

    row = await _row(gate_session, key)
    assert row.cost_usd is not None
    # A declared zero, which is what every provider in this system actually bills.
    assert row.cost_usd == Decimal("0")


async def test_an_adapter_that_prices_nothing_leaves_the_column_null(
    gate_session: AsyncSession,
) -> None:
    """The gate must not invent a zero on an adapter's behalf.

    A NULL here reads as "never priced" and fails T123 loudly. A fabricated `0.00` would be
    indistinguishable from a provider that genuinely bills nothing, which is the same failure
    mode `pricing.yaml` refuses for models (research.md R9).
    """
    adapter = FakeAdapter("unpriced")
    del adapter.cost_usd
    registry.register(adapter)
    key = str(uuid.uuid4())

    await gate.request(
        gate_session,
        run_id=uuid.uuid4(),
        requested_by="ops",
        action_type="unpriced",
        action_request={},
        idempotency_key=key,
    )

    row = await _row(gate_session, key)
    assert row.state == "succeeded"
    assert row.projected_cost_usd is None
    assert row.cost_usd is None


async def test_action_spend_reaches_the_one_combined_total(
    gate_session: AsyncSession,
) -> None:
    """`runs.spend_usd` is one number covering model spend and action spend (FR-052). Every
    real provider bills zero, so a fake with a non-zero cost is the only way to prove the
    action half of that sum is wired at all."""
    registry.register(FakeAdapter("billable", cost_usd=Decimal("1.25")))
    run_id = uuid.uuid4()

    assert await spend_for(gate_session, run_id) == Decimal("0")

    await gate.request(
        gate_session,
        run_id=run_id,
        requested_by="ops",
        action_type="billable",
        action_request={},
        idempotency_key=str(uuid.uuid4()),
    )

    assert await spend_for(gate_session, run_id) == Decimal("1.25")
