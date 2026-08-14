import asyncio

import logfire
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from epyhia.models.tasks import Task
from epyhia.queue import worker as worker_module
from epyhia.queue.worker import HANDLERS, register_handler, run_once, run_worker
from tests.queue.conftest import _insert_task, make_run

KIND = "test_tracing"


async def test_the_worker_entrypoint_configures_tracing(
    queue_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crew runs in this process, so a configuration that only ever ran in `web` left
    every agent untraced. Asserted through the same `session_factory` seam the sweep call
    needed: a call nothing can reach is a call that stays missing."""
    calls = 0

    def _record() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(worker_module, "configure_tracing", _record)

    task = asyncio.create_task(
        run_worker(
            poll_interval_seconds=0.01,
            sweep_interval_seconds=0.0,
            session_factory=async_sessionmaker(
                bind=queue_session.bind, expire_on_commit=False
            ),
        )
    )
    try:
        while calls == 0:
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert calls == 1


async def test_a_handler_runs_with_the_run_id_in_baggage(
    queue_session: AsyncSession,
) -> None:
    """The stack table's claim is `run_id` on *every* span, which is what baggage delivers:
    anything opened under the dispatch inherits it, agent spans included."""
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind=KIND)
    seen: dict[str, object] = {}

    async def handler(session: AsyncSession, task: Task) -> None:
        seen.update(logfire.get_baggage())

    register_handler(KIND, handler)
    try:
        assert await run_once(queue_session) is True
    finally:
        HANDLERS.pop(KIND, None)

    assert seen == {"run_id": str(run_id), "task_kind": KIND}

    # And it is scoped to the dispatch — nothing leaks into the loop that claimed the task.
    assert logfire.get_baggage() == {}

    state = (
        await queue_session.execute(
            text("SELECT state FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).scalar_one()
    assert state == "done"
