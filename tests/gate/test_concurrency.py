import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.gate.errors import ActionInProgress
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

    results = await asyncio.gather(call(), call(), return_exceptions=True)

    assert len(adapter.execute_calls) == 1

    count = (
        await gate_session.execute(
            select(func.count()).select_from(Action).where(Action.idempotency_key == key)
        )
    ).scalar_one()
    assert count == 1

    # The loser resolves one of exactly two ways, both of which are one execution: it arrived
    # while the winner still held the row and was refused by type, or it arrived after the
    # winner finished and read the succeeded row. Nothing else may come back.
    refusals = [r for r in results if isinstance(r, ActionInProgress)]
    outcomes = [r for r in results if not isinstance(r, BaseException)]
    assert len(refusals) + len(outcomes) == 2
    assert all(result["state"] == "succeeded" for result in outcomes)
    assert outcomes, "the winner must return its own result"


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
