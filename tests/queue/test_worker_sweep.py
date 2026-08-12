import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from epyhia.models.tasks import Task
from epyhia.queue.sweeper import TASK_ATTEMPTS_CAP
from epyhia.queue.worker import HANDLERS, register_handler, run_worker
from tests.queue.conftest import _insert_task, make_run

KIND = "test_sweep"


async def _noop(session: AsyncSession, task: Task) -> None:
    """A handler that does nothing, so the loop under test can claim the swept row without
    running a real stage — this file is about the sweep call, not about any agent."""


async def _read(session: AsyncSession, task_id: uuid.UUID) -> tuple[str, int, str | None]:
    row = (
        await session.execute(
            text("SELECT state, attempts, error FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).one()
    return row.state, row.attempts, row.error


async def _until(session: AsyncSession, task_id: uuid.UUID, predicate) -> tuple:
    while True:
        # A fresh snapshot each poll: the loop under test commits from its own sessions.
        await session.rollback()
        state = await _read(session, task_id)
        if predicate(state):
            return state
        await asyncio.sleep(0.02)


async def _run_loop_until(session: AsyncSession, task_id: uuid.UUID, predicate) -> tuple:
    session_factory = async_sessionmaker(bind=session.bind, expire_on_commit=False)
    worker = asyncio.create_task(
        run_worker(
            poll_interval_seconds=0.01,
            sweep_interval_seconds=0.0,
            session_factory=session_factory,
        )
    )
    try:
        return await asyncio.wait_for(_until(session, task_id, predicate), timeout=10)
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker


async def test_worker_loop_reclaims_a_lease_a_dead_worker_left_behind(
    queue_session: AsyncSession,
) -> None:
    """The regression this file exists for.

    `sweep_expired_leases` was correct and thoroughly unit-tested for four phases while the
    production loop never called it, so every crashed run stalled forever against a lease
    nothing swept. `attempts` is the evidence: only the sweeper increments it.
    """
    register_handler(KIND, _noop)
    try:
        run_id = await make_run(queue_session)
        task_id = await _insert_task(
            queue_session,
            run_id,
            kind=KIND,
            state="running",
            lease_expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        _, attempts, _ = await _run_loop_until(
            queue_session, task_id, lambda row: row[1] >= 1
        )
        assert attempts == 1
    finally:
        HANDLERS.pop(KIND, None)


async def test_worker_loop_fails_a_task_past_the_attempts_cap(
    queue_session: AsyncSession,
) -> None:
    """The other half of the sweeper's contract, through the loop: a lease that keeps
    expiring is a task that keeps crashing, and it must stop rather than cycle forever."""
    run_id = await make_run(queue_session)
    task_id = await _insert_task(
        queue_session,
        run_id,
        kind=KIND,
        state="running",
        lease_expires_at=datetime.now(UTC) - timedelta(hours=1),
        attempts=TASK_ATTEMPTS_CAP,
    )

    state, attempts, error = await _run_loop_until(
        queue_session, task_id, lambda row: row[0] == "failed"
    )
    assert state == "failed"
    # Not resurrected into another attempt, and the row says why it stopped.
    assert attempts == TASK_ATTEMPTS_CAP
    assert error == "lease expired past attempts cap"
