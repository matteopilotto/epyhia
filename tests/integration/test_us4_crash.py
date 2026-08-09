import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.api.app import create_app
from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.models.actions import Action
from epyhia.models.tasks import Task
from epyhia.queue.sweeper import sweep_expired_leases
from epyhia.queue.worker import run_once

# Aliased: an un-aliased `test_*` name imported into a test module is collected as a test.
from tests.conftest import test_database_url as _database_url
from tests.integration.test_us1_brief_to_site import (
    FakeDeployAdapter,
    _drive_to_approval,
    load_brief,
)

pytestmark = pytest.mark.asyncio

OPERATOR = "auth0|operator"


@pytest.fixture(autouse=True)
def _vercel_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vercel_token", "test-token")


def client_for(session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_operator] = lambda: {"sub": OPERATOR}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    )


async def _restarted_worker_session() -> AsyncSession:
    """A session belonging to a process that was not there when the pause happened.

    Every fact the resume needs has to come off the `actions` row, so the point of running
    the rest of the test through a connection the parked run never touched is that anything
    held in memory by the first one is gone (R7 step 4).
    """
    engine = create_async_engine(_database_url())
    return async_sessionmaker(bind=engine, expire_on_commit=False)()


async def test_a_kill_at_the_pause_leaves_the_action_actionable(
    integration_session: AsyncSession,
) -> None:
    """The row is in Postgres, so the console re-renders it on reload and the operator's
    click resumes that same keyed action (§7.4, FR-038, SC-008)."""
    adapter = FakeDeployAdapter()
    run_id, action = await _drive_to_approval(
        integration_session, load_brief(), adapter
    )
    action_id = action.id
    assert action.state == "awaiting_approval"

    # The worker dies here. Its lease is gone with it, and so is anything it was holding.
    parked = (
        await integration_session.execute(select(Task).where(Task.kind == "site"))
    ).scalar_one()
    assert parked.state == "awaiting_approval"
    assert parked.lease_expires_at is None
    assert parked.payload["action_id"] == str(action_id)
    await integration_session.close()

    worker = await _restarted_worker_session()
    try:
        # A restarted worker sweeps first. `awaiting_approval` carries no lease and must not
        # be resurrected: re-running the stage would request a second deploy behind the
        # operator's back, which is the approval feature losing idempotency.
        await worker.execute(
            text("UPDATE tasks SET lease_expires_at = now() - interval '1 hour'")
        )
        await worker.commit()
        await sweep_expired_leases(worker)
        await worker.commit()

        assert (
            await worker.scalar(select(Task.state).where(Task.id == parked.id))
        ) == "awaiting_approval"
        assert not await run_once(worker, kind="site")

        # The operator clicks. Once.
        async with client_for(worker) as client:
            approved = await client.post(f"/actions/{action_id}/approve")
            again = await client.post(f"/actions/{action_id}/approve")

        assert approved.status_code == 200
        assert approved.json() == {"state": "awaiting_approval", "approval_decision": "approved"}
        # A second click is not a second action (FR-038).
        assert again.status_code == 409
        assert again.json()["error"] == "not_awaiting_approval"

        resumes = (
            await worker.execute(select(Task).where(Task.kind == "resume"))
        ).scalars().all()
        assert len(resumes) == 1

        assert await run_once(worker, kind="resume")
        assert not await run_once(worker, kind="resume")

        # That same action reached the world — once — and the stage it parked settled.
        resumed = await worker.get(Action, action_id)
        assert resumed.state == "succeeded"
        assert resumed.approved_by == OPERATOR
        assert len(adapter.execute_calls) == 1

        actions = (
            await worker.execute(select(Action).where(Action.run_id == run_id))
        ).scalars().all()
        assert [row.id for row in actions] == [action_id]
        assert (
            await worker.scalar(select(Task.state).where(Task.id == parked.id))
        ) == "done"
    finally:
        bind = worker.bind
        await worker.close()
        await bind.dispose()


async def test_a_click_on_an_already_denied_action_is_not_a_second_action(
    integration_session: AsyncSession,
) -> None:
    """Denial is terminal. A stale console tab clicking approve afterwards must not revive
    the row — the decision, not the state, is what settles it (§6)."""
    adapter = FakeDeployAdapter()
    _, action = await _drive_to_approval(integration_session, load_brief(), adapter)

    async with client_for(integration_session) as client:
        denied = await client.post(f"/actions/{action.id}/deny")
        stale = await client.post(f"/actions/{action.id}/approve")

    assert denied.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["error"] == "not_awaiting_approval"

    await integration_session.refresh(action)
    assert action.state == "denied"
    assert action.approval_decision == "denied"
    assert adapter.execute_calls == []

    resumes = (
        await integration_session.execute(select(Task).where(Task.kind == "resume"))
    ).scalars().all()
    # One resume, carrying the action id and nothing else — the denial still has to reach
    # the stage that parked, or it waits for an approval that will never come.
    assert len(resumes) == 1
    assert resumes[0].payload == {"action_id": str(action.id)}
