import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter


async def test_verify_that_always_fails_retries_to_cap_and_lands_failed(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("test_verify_retry", always_fail_verify=True)
    registry.register(adapter)

    result = await gate.request(
        gate_session,
        run_id=uuid.uuid4(),
        requested_by="marketer",
        action_type="test_verify_retry",
        action_request={},
        idempotency_key=str(uuid.uuid4()),
    )

    assert result["state"] == "failed"
    assert result["state"] != "succeeded"
    assert len(adapter.verify_calls) == gate.MAX_VERIFY_ATTEMPTS
