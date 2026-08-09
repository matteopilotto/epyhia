import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import ops
from epyhia.config import settings
from epyhia.models.actions import Action
from epyhia.models.agent_calls import AgentCall
from epyhia.models.orders import Order
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import run_once
from tests.integration.test_us3_checkout import (
    WEBHOOK_SECRET,
    _ops_model,
    arm,
    client_for,
    completed_event,
    load_brief,
    open_run,
    register_stripe,
    signed,
)
from tests.stripe_stub import FakeStripe

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _stripe_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keys the gate requires. Never real, never leaving the gate — the stub answers."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_stub")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


async def _actions(session: AsyncSession, run_id: uuid.UUID) -> list[tuple]:
    """Every action on the run, with the fields a duplicate would disturb: which row, under
    which key, in which state, with which evidence and which approval.

    Selected as columns rather than entities on purpose. Loading `Action` objects would come
    back through the identity map holding whatever this session already had, so a second pass
    that *did* move a row could compare equal to the first — the test would pass by reading
    its own stale copy.
    """
    rows = (
        await session.execute(
            select(
                Action.id,
                Action.action_type,
                Action.idempotency_key,
                Action.state,
                Action.evidence,
                Action.approval_decision,
                Action.approved_at,
            )
            .where(Action.run_id == run_id)
            .order_by(Action.created_at)
        )
    ).all()
    return [tuple(row) for row in rows]


async def _buy(session: AsyncSession, run: Run, api: FakeStripe, *, event_id: str) -> None:
    """A buyer completes a purchase: one checkout session, one webhook, one order."""
    row = run.resolved_catalogue[0]
    async with client_for(session) as client:
        response = await client.post(
            "/checkout", json={"run_id": str(run.id), "slug": row["slug"]}
        )
    assert response.status_code == 200

    action = (
        await session.execute(
            select(Action).where(
                Action.run_id == run.id, Action.action_type == "checkout_session"
            )
        )
    ).scalar_one()
    event = completed_event(
        event_id=event_id,
        session_id=next(iter(api.checkout.sessions.rows)),
        run_id=run.id,
        row=row,
        key=action.idempotency_key,
    )
    async with client_for(session) as client:
        payload, headers = signed(event)
        recorded = await client.post("/webhooks/stripe", content=payload, headers=headers)
    assert recorded.status_code == 200 and recorded.json()["recorded"] is True


async def test_a_rerun_of_the_money_stage_leaves_one_catalogue_and_one_order(
    integration_session: AsyncSession,
) -> None:
    """The half of US4's independent test the site path does not reach.

    A re-run must produce no second catalogue and no second charge — every Stripe object is
    keyed on `brief_hash + product name + price + billing`, so the second pass short-circuits
    onto the first run's rows rather than creating a parallel set nobody agreed to sell
    (FR-044, §7.2). And it must not park a second approval: the operator already armed this
    catalogue, and asking again would be the approval feature manufacturing the duplicate it
    exists to prevent.
    """
    api = FakeStripe()
    register_stripe(api)
    run = await open_run(integration_session, load_brief())

    armed = await arm(integration_session, run)
    assert armed.state == "succeeded"
    await _buy(integration_session, run, api, event_id="evt_rerun_1")

    baseline = await _actions(integration_session, run.id)
    products = dict(api.products.rows)
    prices = dict(api.prices.rows)
    assert products and prices

    # The re-run. Same brief, same brand doc version, same resolved catalogue — so every key
    # the money stage computes is the one already on file.
    integration_session.add(
        Task(id=uuid.uuid4(), run_id=run.id, kind="money", state="pending")
    )
    await integration_session.commit()
    with ops.agent.override(model=_ops_model()):
        assert await run_once(integration_session, kind="money")

    # One catalogue: nothing was created in the processor the second time round.
    assert api.products.rows == products
    assert api.prices.rows == prices

    # Short-circuited onto the first run's keys: same rows, same states, same evidence, and
    # the same single approval — no second `arm_charge_path` and no re-approval of the first.
    assert await _actions(integration_session, run.id) == baseline
    arm_actions = [row for row in baseline if row[1] == "arm_charge_path"]
    assert len(arm_actions) == 1

    # The stage settled rather than parking for an approval that was already given.
    money_tasks = (
        await integration_session.execute(
            select(Task.state)
            .where(Task.run_id == run.id, Task.kind == "money")
            .order_by(Task.created_at)
        )
    ).scalars().all()
    assert list(money_tasks) == ["done", "done"]

    # And the stage genuinely re-executed rather than being skipped — otherwise every
    # assertion above would hold for the wrong reason. Ops described the catalogue a second
    # time; what it must not do a second time is create it.
    ops_calls = (
        await integration_session.execute(
            select(AgentCall.id).where(AgentCall.run_id == run.id, AgentCall.agent == "ops")
        )
    ).scalars().all()
    assert len(ops_calls) == 2

    # One order: the re-run charged nobody.
    orders = (
        await integration_session.execute(select(Order).where(Order.run_id == run.id))
    ).scalars().all()
    assert len(orders) == 1
