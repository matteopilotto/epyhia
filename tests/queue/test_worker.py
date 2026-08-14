import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents.retry import call_with_retry
from epyhia.artifacts.store import PostgresArtifactStore
from epyhia.models.tasks import Task
from epyhia.queue.claim import DEFAULT_LEASE_MINUTES, claim_task
from epyhia.queue.worker import HANDLERS, register_handler, run_once
from tests.queue.conftest import _insert_task, make_run


@pytest.fixture(autouse=True)
def _clear_handlers():
    HANDLERS.clear()
    yield
    HANDLERS.clear()


async def test_successful_handler_lands_done_and_clears_the_lease(
    queue_session: AsyncSession,
) -> None:
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="plan")

    async def handler(session: AsyncSession, task: Task) -> None:
        pass

    register_handler("plan", handler)

    claimed = await run_once(queue_session)
    assert claimed is True

    row = (
        await queue_session.execute(
            text("SELECT state, lease_expires_at FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).one()
    assert row.state == "done"
    assert row.lease_expires_at is None


async def test_dependent_task_becomes_claimable_once_its_dependency_is_done(
    queue_session: AsyncSession,
) -> None:
    run_id = await make_run(queue_session)
    plan_id = await _insert_task(queue_session, run_id, kind="plan")
    copy_id = await _insert_task(
        queue_session, run_id, kind="copy", depends_on=[plan_id]
    )

    async def noop(session: AsyncSession, task: Task) -> None:
        pass

    register_handler("copy", noop)

    claimed = await run_once(queue_session, kind="copy")
    assert claimed is False

    row = (
        await queue_session.execute(
            text("SELECT state FROM tasks WHERE id = :id"), {"id": copy_id}
        )
    ).one()
    assert row.state == "pending"

    register_handler("plan", noop)
    assert await run_once(queue_session, kind="plan") is True

    assert await run_once(queue_session, kind="copy") is True

    row = (
        await queue_session.execute(
            text("SELECT state FROM tasks WHERE id = :id"), {"id": copy_id}
        )
    ).one()
    assert row.state == "done"


async def test_a_failing_handler_leaves_neither_artifact_nor_done(
    queue_session: AsyncSession,
) -> None:
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="plan")

    store = PostgresArtifactStore()

    async def failing_handler(session: AsyncSession, task: Task) -> None:
        await store.write(
            session,
            run_id=task.run_id,
            kind="copy",
            path="copy.json",
            content_type="application/json",
            content=b"{}",
            grounding_status="clean",
        )
        raise RuntimeError("boom")

    register_handler("plan", failing_handler)

    assert await run_once(queue_session) is True

    row = (
        await queue_session.execute(
            text("SELECT state, error, lease_expires_at FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
    ).one()
    assert row.state == "failed"
    assert row.error == "RuntimeError: boom"
    assert row.lease_expires_at is None

    count = (
        await queue_session.execute(
            text("SELECT count(*) FROM artifacts WHERE run_id = :run_id"), {"run_id": run_id}
        )
    ).scalar_one()
    assert count == 0


async def test_a_stalled_model_call_lands_the_task_failed_and_names_itself(
    queue_session: AsyncSession,
) -> None:
    """A stage whose model call goes silent must end as a legible `failed` row, not as a
    worker parked for the rest of the evening with every other run queued behind it (the
    site stage of run `31b3e4ac`).

    No model is reached here: what the call budget bounds is any awaitable that stops
    producing, so a hanging stream stands in for one.
    """
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="site")
    exits: list[str] = []

    @asynccontextmanager
    async def open_stream() -> AsyncIterator[None]:
        try:
            yield
        finally:
            exits.append("closed")

    async def stalling_handler(session: AsyncSession, task: Task) -> None:
        async def silent_stream() -> str:
            async with open_stream():
                await asyncio.Event().wait()
            raise AssertionError("unreachable")

        await call_with_retry(silent_stream, agent="web_builder", budget_seconds=0.1)

    register_handler("site", stalling_handler)

    assert await run_once(queue_session) is True

    row = (
        await queue_session.execute(
            text("SELECT state, error, lease_expires_at FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
    ).one()
    assert row.state == "failed"
    assert row.error == (
        "ModelCallStalled: web_builder: no response within its 0.1s call budget"
    )
    assert row.lease_expires_at is None
    # The stream was closed, not merely abandoned — that close is what stops the provider
    # generating tokens the run would still be billed for.
    assert exits == ["closed"]


async def test_a_kind_with_no_handler_fails_the_task_rather_than_the_worker(
    queue_session: AsyncSession,
) -> None:
    """A kind no handler module claims — a stage renamed, or a row from an older image.
    Claiming it must not take the process down with it: every other run shares that worker."""
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="not_a_stage")

    assert await run_once(queue_session) is True

    row = (
        await queue_session.execute(
            text("SELECT state, error FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).one()
    assert row.state == "failed"
    assert "no handler registered for task kind: 'not_a_stage'" in row.error


async def test_agent_backed_kinds_get_a_longer_lease_than_the_default(
    queue_session: AsyncSession,
) -> None:
    run_id = await make_run(queue_session)
    await _insert_task(queue_session, run_id, kind="site")

    task = await claim_task(queue_session, kind="site")
    await queue_session.commit()
    assert task is not None

    row = (
        await queue_session.execute(
            text("SELECT lease_expires_at FROM tasks WHERE id = :id"), {"id": task.id}
        )
    ).one()

    threshold = datetime.now(UTC) + timedelta(minutes=DEFAULT_LEASE_MINUTES)
    assert row.lease_expires_at > threshold
