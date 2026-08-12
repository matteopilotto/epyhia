import uuid

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import web_builder
from epyhia.api.app import create_app
from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.gate import gate
from epyhia.models.actions import Action
from epyhia.models.tasks import Task
from epyhia.queue.worker import run_once
from tests.integration.test_us1_brief_to_site import (
    FakeDeployAdapter,
    _drive_to_approval,
    _web_builder_model,
    load_brief,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _vercel_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vercel_token", "test-token")


def client_for(session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_operator] = lambda: {"sub": "auth0|operator"}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test/api"
    )


async def test_re_queueing_a_stage_past_its_gate_action_repeats_no_effect(
    integration_session: AsyncSession,
) -> None:
    """The idempotency claim `POST /tasks/{id}/retry` leans on, asserted rather than assumed
    (T142, §7.2, FR-044).

    A stage can fail *after* its gate action already succeeded — the deploy landed and
    something below it threw. Re-queueing that stage re-requests the same key, which
    short-circuits onto the row that already succeeded and returns its stored evidence: one
    `actions` row, one `execute()`, nothing republished.
    """
    adapter = FakeDeployAdapter()
    run_id, action = await _drive_to_approval(integration_session, load_brief(), adapter)

    await gate.record_approval(integration_session, action.id, "auth0|operator")
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
    assert len(adapter.execute_calls) == 1

    # The stage failed after its deploy was proved. Whatever threw, the world already has the
    # page — which is exactly the case the operator is about to click Retry on.
    site_task = (
        await integration_session.execute(
            select(Task).where(Task.run_id == run_id, Task.kind == "site")
        )
    ).scalar_one()
    await integration_session.execute(
        text("UPDATE tasks SET state = 'failed', error = 'boom' WHERE id = :id"),
        {"id": site_task.id},
    )
    await integration_session.commit()
    # The raw UPDATE moved the row behind the ORM's identity map, and this test hands the
    # router the very session that is holding the stale copy — a request in production gets
    # a fresh one.
    await integration_session.refresh(site_task)
    assert site_task.state == "failed"

    async with client_for(integration_session) as client:
        response = await client.post(f"/tasks/{site_task.id}/retry")
    assert response.status_code == 200, response.json()

    with web_builder.agent.override(model=_web_builder_model()):
        assert await run_once(integration_session, kind="site")

    assert (
        await integration_session.scalar(
            select(func.count()).select_from(Action).where(Action.run_id == run_id)
        )
    ) == 1
    assert len(adapter.execute_calls) == 1
    await integration_session.refresh(site_task)
    assert site_task.state == "done"
