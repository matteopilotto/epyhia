import uuid

import pytest
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.gate.errors import ActionTerminallyFailed


async def test_deny_is_terminal_and_nothing_executes_on_retry(gate_session: AsyncSession) -> None:
    adapter = FakeAdapter("test_deny", requires_approval=True)
    registry.register(adapter)
    run_id = uuid.uuid4()
    key = str(uuid.uuid4())

    with pytest.raises(ApprovalRequired) as exc_info:
        await gate.request(
            gate_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="test_deny",
            action_request={},
            idempotency_key=key,
        )
    action_id = uuid.UUID(exc_info.value.metadata["action_id"])

    deny_result = await gate.deny(gate_session, action_id, approved_by="auth0|operator")
    assert deny_result["state"] == "denied"

    # A subsequent request() on the same key executes nothing, ever — and says so, rather
    # than handing back a result the caller would complete over (T147).
    with pytest.raises(ActionTerminallyFailed) as raised:
        await gate.request(
            gate_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="test_deny",
            action_request={},
            idempotency_key=key,
        )
    assert raised.value.action_id == action_id
    assert raised.value.state == "denied"
    assert len(adapter.execute_calls) == 0
