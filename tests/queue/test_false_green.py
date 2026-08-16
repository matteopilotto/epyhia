import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action
from epyhia.models.tasks import Task
from epyhia.queue.worker import register_handler, run_once
from tests.queue.conftest import _insert_task, make_run

pytestmark = pytest.mark.asyncio


async def test_a_re_queued_task_settles_failed_not_done_over_a_failed_action(
    queue_session: AsyncSession,
) -> None:
    """The false green (T147), reproduced at the layer it was observed: four re-queued
    `publish` tasks read `done` while their action read `failed`, because `request()`
    returned the stored result and the handler completed. The task must land `failed`
    naming the stuck action — the state the re-verify affordance acts on."""
    adapter = FakeAdapter("test_false_green")
    registry.register(adapter)

    run_id = await make_run(queue_session)
    key = str(uuid.uuid4())
    action_id = uuid.uuid4()
    queue_session.add(
        Action(
            id=action_id,
            run_id=run_id,
            requested_by="marketer",
            action_type="test_false_green",
            idempotency_key=key,
            request={"payload": {"text": "the post"}},
            state="failed",
            error="permalink returned 301",
            verify_attempts=5,
        )
    )
    await queue_session.commit()

    async def handler(session: AsyncSession, task: Task) -> None:
        await gate.request(
            session,
            run_id=task.run_id,
            requested_by="marketer",
            action_type="test_false_green",
            action_request={"payload": {"text": "the post"}},
            idempotency_key=key,
            task_id=task.id,
        )

    register_handler("test_false_green_stage", handler)
    task_id = await _insert_task(queue_session, run_id, kind="test_false_green_stage")

    assert await run_once(queue_session, kind="test_false_green_stage")

    state, error = (
        await queue_session.execute(
            text("SELECT state, error FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).one()
    assert state == "failed"
    assert "ActionTerminallyFailed" in error
    assert str(action_id) in error
    # The action itself is untouched: still failed, still awaiting its re-verify — and
    # nothing executed for its key.
    reread = await queue_session.scalar(select(Action).where(Action.id == action_id))
    assert reread.state == "failed"
    assert adapter.execute_calls == []
    registry.clear()
