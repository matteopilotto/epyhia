import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.gate.errors import ActionTerminallyFailed
from epyhia.models.actions import Action


async def _terminal(session: AsyncSession, action_type: str, state: str) -> Action:
    """A row that already burned to a terminal state — the 19 publish rows' shape (T147)."""
    action = Action(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        requested_by="marketer",
        action_type=action_type,
        idempotency_key=str(uuid.uuid4()),
        request={"marker": "already terminal"},
        state=state,
        error="verify burned its attempts" if state == "failed" else None,
    )
    session.add(action)
    await session.commit()
    return action


@pytest.mark.parametrize("state", ["failed", "denied"])
async def test_request_on_a_failed_or_denied_row_raises_naming_the_action(
    gate_session: AsyncSession, state: str
) -> None:
    """The false-green defect (T147): `request()` returned the stored failed result, every
    caller ignored it, and the worker wrote `done` over an unproved effect. The raise is
    what lands the re-queued task `failed` naming the stuck action instead."""
    adapter = FakeAdapter(f"test_terminal_{state}")
    registry.register(adapter)
    action = await _terminal(gate_session, adapter.action_type, state)

    with pytest.raises(ActionTerminallyFailed) as raised:
        await gate.request(
            gate_session,
            run_id=action.run_id,
            requested_by="marketer",
            action_type=adapter.action_type,
            action_request={"marker": "re-queued"},
            idempotency_key=action.idempotency_key,
        )

    assert raised.value.action_id == action.id
    assert raised.value.state == state
    assert str(action.id) in str(raised.value)
    # Terminal means terminal: the raise must not come with a re-execution.
    assert adapter.execute_calls == []


async def test_request_on_a_succeeded_row_still_returns_its_evidence_silently(
    gate_session: AsyncSession,
) -> None:
    """T142's promise intact: only `succeeded` short-circuits silently, because it is the
    one terminal state whose stored result proves the effect (FR-045)."""
    adapter = FakeAdapter("test_terminal_succeeded")
    registry.register(adapter)
    key = str(uuid.uuid4())
    run_id = uuid.uuid4()

    first = await gate.request(
        gate_session,
        run_id=run_id,
        requested_by="ops",
        action_type=adapter.action_type,
        action_request={"n": 1},
        idempotency_key=key,
    )
    second = await gate.request(
        gate_session,
        run_id=run_id,
        requested_by="ops",
        action_type=adapter.action_type,
        action_request={"n": 1},
        idempotency_key=key,
    )

    assert first["state"] == second["state"] == "succeeded"
    assert second["evidence"] == first["evidence"]
    assert len(adapter.execute_calls) == 1
