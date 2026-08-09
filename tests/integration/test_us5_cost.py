from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import marketer, reviewer, strategist, web_builder
from epyhia.api.app import create_app
from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.cost.pricing import rate_for
from epyhia.models.agent_calls import AgentCall
from epyhia.queue.worker import run_once
from tests.integration.test_us1_brief_to_site import (
    FakeDeployAdapter,
    _drive_to_approval,
    _marketer_model,
    _open_run,
    _reviewer_model,
    _strategist_model,
    _web_builder_model,
    load_brief,
)

OPERATOR = "auth0|operator"

# The tier the planning model is priced at, read from `pricing.yaml` through the same
# function the ledger uses. SC-007's "top tier" is whatever the rate table says it is, so
# nothing here restates it as a literal.
PLANNING_TIER = rate_for(strategist.MODEL_ID, datetime.now(UTC)).tier


def client_for(session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_operator] = lambda: {"sub": OPERATOR}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    )


@pytest.fixture(autouse=True)
def _vercel_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from epyhia.config import settings

    monkeypatch.setattr(settings, "vercel_token", "test-token")


async def _drive_run(session: AsyncSession):
    """A real run through plan → copy → site: four model calls across all three tiers, each
    one recorded by the ledger from the usage the model actually reported."""
    brief_payload = load_brief()
    run_id, _ = await _open_run(session, brief_payload)

    with strategist.agent.override(model=_strategist_model(brief_payload)):
        assert await run_once(session, kind="plan")
    with (
        marketer.agent.override(model=_marketer_model()),
        reviewer.agent.override(model=_reviewer_model()),
    ):
        assert await run_once(session, kind="copy")
    with web_builder.agent.override(model=_web_builder_model()):
        assert await run_once(session, kind="site")

    return run_id


async def test_every_call_carries_a_tier_and_a_cost(
    integration_session: AsyncSession,
) -> None:
    run_id = await _drive_run(integration_session)

    calls = (
        await integration_session.execute(select(AgentCall).where(AgentCall.run_id == run_id))
    ).scalars().all()
    assert len(calls) > 1

    for call in calls:
        assert call.tier is not None
        assert call.cost_usd is not None
        # The tier is the rate table's, not one inferred from the model id — the two have
        # exactly one definition (research.md R9).
        rate = rate_for(call.model_id, call.created_at)
        assert call.tier == rate.tier
        # Every call in this run really went to a model, so a zero cost here would mean a
        # rate quietly defaulted rather than a call that happened not to spend.
        assert call.input_tokens + call.output_tokens > 0
        assert call.cost_usd > 0

    # SC-007: exactly one top-tier call per run, and it is the Strategist's. A second one is
    # a real defect — a planning-tier model reached for where a cheaper one belongs.
    planning = [call for call in calls if call.tier == PLANNING_TIER]
    assert len(planning) == 1
    assert planning[0].agent == strategist.AGENT
    assert planning[0].model_id == strategist.MODEL_ID


async def test_cost_endpoint_itemises_calls_under_one_total(
    integration_session: AsyncSession,
) -> None:
    run_id = await _drive_run(integration_session)

    async with client_for(integration_session) as client:
        response = await client.get(f"/runs/{run_id}/cost")
    assert response.status_code == 200
    body = response.json()

    calls = (
        await integration_session.execute(select(AgentCall).where(AgentCall.run_id == run_id))
    ).scalars().all()
    assert len(body["calls"]) == len(calls)

    for row in body["calls"]:
        assert row["tier"] is not None
        assert float(row["cost_usd"]) > 0
        assert row["latency_ms"] >= 0
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_write_tokens",
            "cache_read_tokens",
        ):
            assert field in row

    # One total against one budget (FR-052). It covers this run's action spend too, so it is
    # never below the model spend it itemises.
    assert float(body["total_usd"]) >= sum(float(row["cost_usd"]) for row in body["calls"])
    assert float(body["budget_usd"]) > 0


async def test_cost_is_answerable_per_stage(integration_session: AsyncSession) -> None:
    """The checkpoint asks for cost per call, per stage and per run. Per stage is not per
    agent: the run has to be able to say what `copy` cost as distinct from what `site` did."""
    run_id = await _drive_run(integration_session)

    async with client_for(integration_session) as client:
        body = (await client.get(f"/runs/{run_id}/cost")).json()

    assert all(row["stage"] is not None for row in body["calls"])

    subtotals: dict[str, float] = {}
    for row in body["calls"]:
        subtotals[row["stage"]] = subtotals.get(row["stage"], 0) + float(row["cost_usd"])

    # Every stage this run actually ran is priced, named by the task's own `kind` rather than
    # by a list of stage names written here.
    ran = set(
        (
            await integration_session.execute(
                text("SELECT kind FROM tasks WHERE run_id = :r AND state = 'done'"),
                {"r": run_id},
            )
        ).scalars()
    )
    assert ran <= set(subtotals)
    assert all(value > 0 for value in subtotals.values())
    # More than one stage billed, or "per stage" would be indistinguishable from "per run".
    assert len(subtotals) > 1


async def test_one_total_holds_while_a_run_is_parked_at_an_approval(
    integration_session: AsyncSession,
) -> None:
    """`GET /runs` and `GET /runs/{id}/cost` must not disagree about what a run has spent.

    A stage that generates and then parks for an approval is the case that splits them: the
    spend is real and committed, and a roll-up written only on the *next* claim would leave
    the run list showing one number and the cost view another — FR-052's two separate views,
    arriving by the back door.
    """
    run_id, action = await _drive_to_approval(
        integration_session, load_brief(), FakeDeployAdapter()
    )
    assert action.state == "awaiting_approval"

    async with client_for(integration_session) as client:
        run = (await client.get(f"/runs/{run_id}")).json()
        cost = (await client.get(f"/runs/{run_id}/cost")).json()

    assert Decimal(run["spend_usd"]) == Decimal(cost["total_usd"])
    assert Decimal(run["spend_usd"]) > 0
