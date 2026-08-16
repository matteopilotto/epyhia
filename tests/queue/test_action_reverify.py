import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action
from epyhia.models.tasks import Task
from epyhia.queue.handlers import resume as resume_handler  # noqa: F401  — registers "resume"
from epyhia.queue.worker import run_once
from tests.queue.conftest import _insert_task, make_run
from tests.queue.test_task_retry import client_for

pytestmark = pytest.mark.asyncio


async def _insert_action(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    action_type: str = "test_reverify",
    state: str = "failed",
    result: dict | None = None,
    task_id: uuid.UUID | None = None,
) -> uuid.UUID:
    action_id = uuid.uuid4()
    session.add(
        Action(
            id=action_id,
            run_id=run_id,
            task_id=task_id,
            requested_by="marketer",
            action_type=action_type,
            idempotency_key=str(uuid.uuid4()),
            request={"payload": {"body": "the post"}},
            state=state,
            result=result,
            # `succeeded` requires evidence by constraint (ck_actions_succeeded_evidence).
            evidence={"status": "ok"} if state == "succeeded" else None,
            error="permalink returned 301" if state == "failed" else None,
            verify_attempts=5 if state == "failed" else 0,
        )
    )
    await session.commit()
    return action_id


async def test_a_failed_action_with_a_result_reopens_verification(
    queue_session: AsyncSession,
) -> None:
    """The T146 affordance: state → `verifying`, attempts and error reset, and a `resume`
    task enqueued — the same shape the approve endpoint uses, so no new drive path."""
    run_id = await make_run(queue_session)
    action_id = await _insert_action(
        queue_session, run_id, result={"permalink": "https://sink.invalid/posts/1"}
    )

    async with client_for(queue_session) as client:
        response = await client.post(f"/actions/{action_id}/reverify")

    assert response.status_code == 200
    assert response.json() == {"state": "verifying"}

    action = await queue_session.get(Action, action_id)
    await queue_session.refresh(action)
    assert (action.state, action.verify_attempts, action.error) == ("verifying", 0, None)

    resume_task = await queue_session.scalar(
        select(Task).where(Task.run_id == run_id, Task.kind == "resume")
    )
    assert resume_task is not None
    assert resume_task.state == "pending"
    assert resume_task.payload == {"action_id": str(action_id)}


async def test_the_resume_heals_the_action_and_flips_its_task_off_the_probe(
    queue_session: AsyncSession,
) -> None:
    """The remediation end to end: re-verify, worker picks up the resume, the probe proves
    the effect, and `_settle` turns the stage's `failed` into an honest `done` — which is
    what empties the runbook of mass task-retries."""
    adapter = FakeAdapter("test_reverify_heal")
    registry.register(adapter)
    run_id = await make_run(queue_session)
    task_id = await _insert_task(queue_session, run_id, kind="publish", state="failed")
    action_id = await _insert_action(
        queue_session,
        run_id,
        action_type="test_reverify_heal",
        result={"handle": "stored-by-execute"},
        task_id=task_id,
    )

    async with client_for(queue_session) as client:
        assert (await client.post(f"/actions/{action_id}/reverify")).status_code == 200

    assert await run_once(queue_session, kind="resume")

    action = await queue_session.get(Action, action_id)
    await queue_session.refresh(action)
    assert action.state == "succeeded"
    assert action.evidence == {"status": "ok"}
    # verify() probed with the stored result; execute() never ran again.
    assert adapter.verify_results == [{"handle": "stored-by-execute"}]
    assert adapter.execute_calls == []

    task_state = (
        await queue_session.execute(
            text("SELECT state FROM tasks WHERE id = :id"), {"id": task_id}
        )
    ).scalar_one()
    assert task_state == "done"
    registry.clear()


async def test_a_failed_action_without_a_result_is_refused(
    queue_session: AsyncSession,
) -> None:
    """A failure at execute() — or a pre-migration row — has nothing recorded to prove.
    Re-opening it would burn five attempts to say `failed` again (the send_email row's
    case: no message was ever sent, so re-verification is the wrong remedy)."""
    run_id = await make_run(queue_session)
    action_id = await _insert_action(queue_session, run_id, result=None)

    async with client_for(queue_session) as client:
        response = await client.post(f"/actions/{action_id}/reverify")

    assert response.status_code == 409
    assert response.json()["error"] == "not_reverifiable"
    action = await queue_session.get(Action, action_id)
    assert action.state == "failed"


@pytest.mark.parametrize("state", ["pending", "awaiting_approval", "verifying", "succeeded"])
async def test_only_a_failed_action_is_reverifiable(
    queue_session: AsyncSession, state: str
) -> None:
    run_id = await make_run(queue_session)
    action_id = await _insert_action(
        queue_session, run_id, state=state, result={"handle": "x"}
    )

    async with client_for(queue_session) as client:
        response = await client.post(f"/actions/{action_id}/reverify")

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "not_reverifiable"
    assert body["state"] == state


async def test_an_unknown_action_is_a_404(queue_session: AsyncSession) -> None:
    async with client_for(queue_session) as client:
        response = await client.post(f"/actions/{uuid.uuid4()}/reverify")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
