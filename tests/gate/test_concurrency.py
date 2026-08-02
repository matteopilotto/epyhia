import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action


async def test_concurrent_requests_on_one_key_produce_one_execution_and_one_row(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("test_concurrency")
    registry.register(adapter)
    run_id = uuid.uuid4()
    key = str(uuid.uuid4())

    session_factory = async_sessionmaker(bind=gate_session.bind, expire_on_commit=False)

    async def call() -> dict:
        async with session_factory() as session:
            return await gate.request(
                session,
                run_id=run_id,
                requested_by="marketer",
                action_type="test_concurrency",
                action_request={"n": 1},
                idempotency_key=key,
            )

    results = await asyncio.gather(call(), call())

    assert len(adapter.execute_calls) == 1

    count = (
        await gate_session.execute(
            select(func.count()).select_from(Action).where(Action.idempotency_key == key)
        )
    ).scalar_one()
    assert count == 1

    states = {result["state"] for result in results}
    assert states <= {"succeeded", "executing", "verifying", "pending"}
    assert "succeeded" in states or any(r.get("in_progress") for r in results)


async def test_second_caller_reads_first_callers_result(gate_session: AsyncSession) -> None:
    registry.register(FakeAdapter("test_concurrency_seq"))
    run_id = uuid.uuid4()
    key = str(uuid.uuid4())

    engine = gate_session.bind
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_factory() as first_session:
        first_result = await gate.request(
            first_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="test_concurrency_seq",
            action_request={"n": 1},
            idempotency_key=key,
        )

    async with session_factory() as second_session:
        second_result = await gate.request(
            second_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="test_concurrency_seq",
            action_request={"n": 1},
            idempotency_key=key,
        )

    assert second_result["state"] == first_result["state"] == "succeeded"
    assert second_result["evidence"] == first_result["evidence"]
