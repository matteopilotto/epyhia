import copy
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import marketer, reviewer, strategist
from epyhia.api.app import create_app
from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.cost.budget import HALTED, daily_spend
from epyhia.gate import gate
from epyhia.models.agent_calls import AgentCall
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import run_once
from tests.integration.test_us1_brief_to_site import (
    FakeDeployAdapter,
    _drive_to_approval,
    _marketer_model,
    _open_run,
    _reviewer_model,
    _strategist_model,
    load_brief,
)

OPERATOR = "auth0|operator"


def client_for(session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_operator] = lambda: {"sub": OPERATOR}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test/api"
    )


@pytest.fixture(autouse=True)
def _vercel_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vercel_token", "test-token")


async def _set_budget(session: AsyncSession, run_id: uuid.UUID, budget: Decimal) -> None:
    await session.execute(
        text("UPDATE runs SET budget_usd = :budget WHERE id = :id"),
        {"budget": budget, "id": run_id},
    )
    await session.commit()


async def _call_count(session: AsyncSession, run_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count()).select_from(AgentCall).where(AgentCall.run_id == run_id)
    )


async def test_a_run_crossing_its_budget_stops_spending(
    integration_session: AsyncSession,
) -> None:
    """The budget is crossed by real model spend, not by a number typed onto the row: the
    plan stage runs a real Strategist call and the ledger prices it through `pricing.yaml`."""
    brief_payload = load_brief()
    run_id, _ = await _open_run(integration_session, brief_payload)
    # Below anything a single call can cost, so the first stage crosses it. The stage still
    # runs — the check is "stop starting new work", not "predict what the next call costs".
    await _set_budget(integration_session, run_id, Decimal("0.0000001"))

    with strategist.agent.override(model=_strategist_model(brief_payload)):
        assert await run_once(integration_session, kind="plan")

    run = await integration_session.get(Run, run_id)
    await integration_session.refresh(run)
    assert run.status == HALTED
    # One number, and it is real: model spend the ledger derived, plus action spend.
    assert run.spend_usd > 0
    assert run.spend_usd >= run.budget_usd

    spent_calls = await _call_count(integration_session, run_id)

    # The next stage is claimed and refused rather than run. `copy` would otherwise be two
    # more model calls, so this is the assertion that the run stopped spending.
    with (
        marketer.agent.override(model=_marketer_model()),
        reviewer.agent.override(model=_reviewer_model()),
    ):
        assert await run_once(integration_session, kind="copy")

    assert await _call_count(integration_session, run_id) == spent_calls
    refused = (
        await integration_session.execute(
            text("SELECT state, error FROM tasks WHERE run_id = :id AND kind = 'copy'"),
            {"id": run_id},
        )
    ).one()
    assert refused.state == "failed"
    assert HALTED in refused.error


async def test_halting_does_not_abandon_an_action_already_in_flight(
    integration_session: AsyncSession,
) -> None:
    """Halting stops new work; it is not a shortcut around the gate.

    The run crosses its budget while a deploy sits `awaiting_approval`. The approval is still
    honoured, the action is still driven through its `verify()` probe, and `succeeded` still
    arrives carrying evidence — none of which the halt is allowed to skip.
    """
    brief_payload = load_brief()
    adapter = FakeDeployAdapter()
    run_id, action = await _drive_to_approval(integration_session, brief_payload, adapter)
    assert action.state == "awaiting_approval"

    await _set_budget(integration_session, run_id, Decimal("0.0000001"))

    await gate.record_approval(integration_session, action.id, OPERATOR)
    integration_session.add(
        Task(
            id=uuid.uuid4(),
            run_id=run_id,
            kind="resume",
            state="pending",
            payload={"action_id": str(action.id)},
        )
    )
    await integration_session.commit()
    assert await run_once(integration_session, kind="resume")

    await integration_session.refresh(action)
    assert action.state == "succeeded"
    assert action.evidence is not None

    # And the run is halted all the same — the exemption is for the action in flight, not a
    # licence to keep going.
    run = await integration_session.get(Run, run_id)
    await integration_session.refresh(run)
    assert run.status == HALTED


async def test_the_daily_ceiling_stops_a_new_run_starting(
    integration_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    brief_payload = load_brief()
    run_id, _ = await _open_run(integration_session, brief_payload)
    with strategist.agent.override(model=_strategist_model(brief_payload)):
        assert await run_once(integration_session, kind="plan")

    # The ceiling is set from what the day has actually spent, so this fires against real
    # accumulated cost rather than a number invented for the test.
    spent_today = await daily_spend(integration_session)
    assert spent_today > 0
    monkeypatch.setattr(settings, "daily_ceiling_usd", str(spent_today))

    second = copy.deepcopy(brief_payload)
    second["one_liner"] = f"{second['one_liner']} — resubmitted under a different hash"

    async with client_for(integration_session) as client:
        refused = await client.post("/briefs", json=second)
        # A byte-identical resubmission opens no run, so the ceiling has nothing to refuse:
        # it still resolves to the run that already exists (FR-002).
        deduplicated = await client.post("/briefs", json=brief_payload)

    assert refused.status_code == 503
    assert refused.json()["error"] == "daily_ceiling_reached"

    assert deduplicated.status_code == 200
    assert deduplicated.json()["deduplicated"] is True
    assert deduplicated.json()["run_id"] == str(run_id)

    # Nothing was opened and nothing was screened: one brief, one run, still.
    assert await integration_session.scalar(select(func.count()).select_from(Brief)) == 1
    assert await integration_session.scalar(select(func.count()).select_from(Run)) == 1


async def test_an_unset_run_budget_is_a_sentence_not_a_stack_trace(
    integration_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-064: the app starts with nothing configured and fails at the seam that needs the
    value — before the guardrail's model call, so the refusal costs nothing."""
    monkeypatch.setattr(settings, "run_budget_usd", None)
    monkeypatch.setattr(settings, "daily_ceiling_usd", None)

    async with client_for(integration_session) as client:
        response = await client.post("/briefs", json=load_brief())

    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "budget_not_configured"
    assert "RUN_BUDGET_USD" in body["detail"]
    assert await integration_session.scalar(select(func.count()).select_from(Run)) == 0
