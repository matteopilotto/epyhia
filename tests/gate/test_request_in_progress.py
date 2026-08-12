import uuid

import pytest
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.gate.errors import ActionInProgress
from epyhia.models.actions import Action


async def _stranded(session: AsyncSession, action_type: str, state: str) -> Action:
    """A row a killed worker left mid-flight: past `pending`, short of terminal."""
    action = Action(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        requested_by="ops",
        action_type=action_type,
        idempotency_key=str(uuid.uuid4()),
        request={"marker": "stranded"},
        state=state,
    )
    session.add(action)
    await session.commit()
    return action


@pytest.mark.parametrize("state", ["executing", "verifying"])
async def test_request_on_an_in_flight_row_refuses_by_type(
    gate_session: AsyncSession, state: str
) -> None:
    """The caller must not be handed a result-shaped dict it can unpack past.

    `wire_catalogue` reads `product["evidence"]["product_id"]` straight off this return. When
    the shape carried no evidence the money stage died on `KeyError: 'evidence'`, naming
    neither the action nor the reason — in a system whose standard is a named refusal.
    """
    adapter = FakeAdapter(f"test_in_flight_{state}")
    registry.register(adapter)
    action = await _stranded(gate_session, adapter.action_type, state)

    with pytest.raises(ActionInProgress) as raised:
        await gate.request(
            gate_session,
            run_id=action.run_id,
            requested_by="ops",
            action_type=adapter.action_type,
            action_request={"marker": "second attempt"},
            idempotency_key=action.idempotency_key,
        )

    assert raised.value.action_id == action.id
    assert raised.value.state == state
    # A second request() must never be a second execution — that is the whole reason the
    # gate refuses rather than re-driving (§7.2).
    assert adapter.execute_calls == []


async def test_request_on_a_parked_approval_parks_again_rather_than_failing(
    gate_session: AsyncSession,
) -> None:
    """A re-run of a stage whose action is awaiting a human is waiting, not failing.

    Observed on run 8d89a987: a deploy restarted the worker mid-stage, the sweeper correctly
    re-ran it, and the re-run found its own deploy parked `awaiting_approval` and landed the
    task `failed` — while the operator was still looking at the approval. Their click then
    resumed an action whose stage had already given up.
    """
    adapter = FakeAdapter("test_in_flight_parked", requires_approval=True)
    registry.register(adapter)
    action = await _stranded(gate_session, adapter.action_type, "awaiting_approval")

    with pytest.raises(ApprovalRequired) as raised:
        await gate.request(
            gate_session,
            run_id=action.run_id,
            requested_by="web_builder",
            action_type=adapter.action_type,
            action_request={"marker": "second attempt"},
            idempotency_key=action.idempotency_key,
        )

    # Carries the parked row's id, so the task re-parks against the action the operator is
    # actually looking at rather than one of its own.
    assert raised.value.metadata["action_id"] == str(action.id)
    assert adapter.execute_calls == []


async def test_request_on_a_terminal_row_still_returns_its_evidence(
    gate_session: AsyncSession,
) -> None:
    """The contract that must not regress: a genuine re-run against a finished key reads the
    first run's result, which is what makes a re-run produce no second effect (FR-045)."""
    adapter = FakeAdapter("test_in_flight_terminal")
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
