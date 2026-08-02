import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action


async def test_crash_mid_executing_resumes_into_verifying_and_probe_decides(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("test_crash_resume")
    registry.register(adapter)

    # Simulate a process that crashed after moving the row to "executing" but before
    # calling execute() to completion — no execute() call has ever happened for this row.
    action = Action(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        requested_by="web_builder",
        action_type="test_crash_resume",
        idempotency_key=str(uuid.uuid4()),
        request={"marker": "abandoned"},
        state="executing",
    )
    gate_session.add(action)
    await gate_session.commit()

    result = await gate.resume(gate_session, action.id)

    # The row never went through execute() again — it short-circuited straight to verifying.
    assert len(adapter.execute_calls) == 0
    assert len(adapter.verify_calls) == 1
    assert result["state"] == "succeeded"
    assert result["evidence"] == {"status": "ok"}


async def test_crash_resume_outcome_comes_from_the_probe_not_the_stored_status(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("test_crash_resume_fail", always_fail_verify=True)
    registry.register(adapter)

    action = Action(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        requested_by="web_builder",
        action_type="test_crash_resume_fail",
        idempotency_key=str(uuid.uuid4()),
        request={},
        state="executing",
    )
    gate_session.add(action)
    await gate_session.commit()

    result = await gate.resume(gate_session, action.id)

    assert result["state"] == "failed"
