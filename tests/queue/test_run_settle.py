import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.queue import worker
from epyhia.queue.settle import settle_run
from epyhia.queue.sweeper import sweep_expired_leases
from epyhia.queue.worker import run_once
from tests.queue.conftest import _insert_task, make_run

pytestmark = pytest.mark.asyncio


async def _status(session: AsyncSession, run_id: uuid.UUID) -> str:
    return (
        await session.execute(
            text("SELECT status FROM runs WHERE id = :id"), {"id": run_id}
        )
    ).scalar_one()


async def _noop(session: AsyncSession, task) -> None:
    return None


async def _boom(session: AsyncSession, task) -> None:
    raise RuntimeError("handler exploded")


async def test_a_run_settles_succeeded_when_its_last_stage_lands_done(
    queue_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T144. `runs.status` had no path to `succeeded` — a run whose every stage was `done`
    read `running` forever and its SSE timeline never closed. The writer sits where the
    queue settles a task, so the run settles with its last stage and not on a poll."""
    run_id = await make_run(queue_session)
    await _insert_task(queue_session, run_id, kind="plan")
    await _insert_task(queue_session, run_id, kind="site")
    monkeypatch.setitem(worker.HANDLERS, "plan", _noop)
    monkeypatch.setitem(worker.HANDLERS, "site", _noop)

    assert await run_once(queue_session)
    # One stage down, one still pending: the run is not settled by a stage that merely
    # finished — only by the last one.
    assert await _status(queue_session, run_id) == "running"

    assert await run_once(queue_session)
    assert await _status(queue_session, run_id) == "succeeded"


async def test_a_run_settles_failed_when_a_dead_stage_is_its_last(
    queue_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await make_run(queue_session)
    await _insert_task(queue_session, run_id, kind="plan")
    monkeypatch.setitem(worker.HANDLERS, "plan", _boom)

    assert await run_once(queue_session)
    assert await _status(queue_session, run_id) == "failed"


async def test_a_parked_approval_keeps_the_run_unsettled(
    queue_session: AsyncSession,
) -> None:
    """An `awaiting_approval` stage can still move, so the run around it is still running —
    settling it would close the SSE stream an operator is watching for the approval."""
    run_id = await make_run(queue_session)
    await _insert_task(queue_session, run_id, kind="plan", state="done")
    await _insert_task(queue_session, run_id, kind="site", state="awaiting_approval")

    await settle_run(queue_session, run_id)
    await queue_session.commit()
    assert await _status(queue_session, run_id) == "running"


async def test_a_halted_run_is_never_overwritten_by_a_settle(
    queue_session: AsyncSession,
) -> None:
    """`halted_budget` is the budget's verdict, not the queue's — every stage being `done`
    does not make an over-budget run a success."""
    run_id = await make_run(queue_session)
    await queue_session.execute(
        text("UPDATE runs SET status = 'halted_budget' WHERE id = :id"), {"id": run_id}
    )
    await _insert_task(queue_session, run_id, kind="plan", state="done")
    await queue_session.commit()

    await settle_run(queue_session, run_id)
    await queue_session.commit()
    assert await _status(queue_session, run_id) == "halted_budget"


async def test_the_sweepers_past_the_cap_failure_settles_the_run_too(
    queue_session: AsyncSession,
) -> None:
    """The one task-settle point outside the worker loop. A stage whose lease lapsed past
    the attempts cap lands `failed` with no worker attached — without the settle here, the
    run around it would read `running` forever, the exact defect T144 filed."""
    run_id = await make_run(queue_session)
    expired = datetime.now(UTC) - timedelta(minutes=1)
    await _insert_task(
        queue_session, run_id, kind="plan", state="running",
        lease_expires_at=expired, attempts=5,
    )

    await sweep_expired_leases(queue_session)
    await queue_session.commit()
    assert await _status(queue_session, run_id) == "failed"
