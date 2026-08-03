import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from epyhia.queue.claim import claim_task
from epyhia.queue.sweeper import sweep_expired_leases
from tests.queue.conftest import _insert_task, make_run


async def test_two_concurrent_claims_get_distinct_rows(queue_session: AsyncSession) -> None:
    run_id = await make_run(queue_session)
    first_id = await _insert_task(queue_session, run_id)
    second_id = await _insert_task(queue_session, run_id)

    session_factory = async_sessionmaker(bind=queue_session.bind, expire_on_commit=False)

    async def claim_once() -> uuid.UUID | None:
        async with session_factory() as session:
            task = await claim_task(session)
            await session.commit()
            return task.id if task else None

    claimed_ids = await asyncio.gather(claim_once(), claim_once())

    assert None not in claimed_ids
    assert set(claimed_ids) == {first_id, second_id}


async def test_expired_lease_is_reclaimable_after_sweep(queue_session: AsyncSession) -> None:
    run_id = await make_run(queue_session)
    task_id = await _insert_task(
        queue_session,
        run_id,
        state="claimed",
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    await sweep_expired_leases(queue_session)
    await queue_session.commit()

    row = (
        await queue_session.execute(
            text("SELECT state, attempts FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).one()
    assert row.state == "pending"
    assert row.attempts == 1

    claimed = await claim_task(queue_session)
    assert claimed is not None
    assert claimed.id == task_id


async def test_awaiting_approval_row_left_alone_by_sweeper(queue_session: AsyncSession) -> None:
    run_id = await make_run(queue_session)
    task_id = await _insert_task(
        queue_session,
        run_id,
        state="awaiting_approval",
        lease_expires_at=None,
    )

    await sweep_expired_leases(queue_session)
    await queue_session.commit()

    row = (
        await queue_session.execute(text("SELECT state FROM tasks WHERE id = :id"), {"id": task_id})
    ).one()
    assert row.state == "awaiting_approval"
