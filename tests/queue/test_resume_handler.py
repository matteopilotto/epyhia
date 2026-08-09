import uuid

import pytest
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action
from epyhia.models.tasks import Task
from epyhia.queue.handlers import resume as resume_handler  # noqa: F401  — registers "resume"
from epyhia.queue.worker import run_once
from tests.queue.conftest import _insert_task, make_run

pytestmark = pytest.mark.asyncio


async def _park_at_approval(
    session: AsyncSession, *, run_id: uuid.UUID, task_id: uuid.UUID, action_type: str
) -> Action:
    """Drive a stage task up to the pause the way a handler does, and park it there."""
    with pytest.raises(ApprovalRequired):
        await gate.request(
            session,
            run_id=run_id,
            requested_by="test",
            action_type=action_type,
            action_request={},
            idempotency_key=f"{action_type}:{task_id}",
            task_id=task_id,
        )
    await session.execute(
        text("UPDATE tasks SET state = 'awaiting_approval' WHERE id = :id"), {"id": task_id}
    )
    await session.commit()
    return await session.scalar(select(Action.id).where(Action.task_id == task_id))


async def _enqueue_resume(session: AsyncSession, run_id: uuid.UUID, action_id: uuid.UUID) -> None:
    session.add(
        Task(
            id=uuid.uuid4(),
            run_id=run_id,
            kind="resume",
            state="pending",
            payload={"action_id": str(action_id)},
        )
    )
    await session.commit()


async def _task_state(session: AsyncSession, task_id: uuid.UUID) -> str:
    return await session.scalar(select(Task.state).where(Task.id == task_id))


async def test_approved_action_settles_the_stage_that_parked(
    queue_session: AsyncSession,
) -> None:
    registry.register(FakeAdapter("test_resume_ok", requires_approval=True))
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="money")

    action_id = await _park_at_approval(
        queue_session, run_id=run_id, task_id=task_id, action_type="test_resume_ok"
    )
    await gate.record_approval(queue_session, action_id, "operator@test")
    await _enqueue_resume(queue_session, run_id, action_id)

    assert await run_once(queue_session, kind="resume")

    assert await _task_state(queue_session, task_id) == "done"
    registry.clear()


async def test_a_failing_execute_does_not_strand_the_stage_at_the_pause(
    queue_session: AsyncSession,
) -> None:
    """The pause is one-way: the decision is already on the action row, so a second click
    gets `not_awaiting_approval` and the sweeper leaves `awaiting_approval` alone. If the
    resume let the exception out before settling, the run would park there for good."""
    registry.register(
        FakeAdapter("test_resume_boom", requires_approval=True, fail_execute=True)
    )
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="money")

    action_id = await _park_at_approval(
        queue_session, run_id=run_id, task_id=task_id, action_type="test_resume_boom"
    )
    await gate.record_approval(queue_session, action_id, "operator@test")
    await _enqueue_resume(queue_session, run_id, action_id)

    assert await run_once(queue_session, kind="resume")

    assert await _task_state(queue_session, task_id) == "failed"
    action = await queue_session.get(Action, action_id)
    assert action.state == "failed"
    registry.clear()
