import uuid

import pytest
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.models.actions import Action


async def test_approval_required_action_lands_awaiting_approval_before_raise(
    gate_session: AsyncSession, fresh_session: AsyncSession
) -> None:
    registry.register(FakeAdapter("test_approval", requires_approval=True))
    run_id = uuid.uuid4()
    key = str(uuid.uuid4())

    with pytest.raises(ApprovalRequired):
        await gate.request(
            gate_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="test_approval",
            action_request={"to": "buyer@example.com"},
            idempotency_key=key,
        )

    # A fresh session — a different connection entirely — must see the durable row.
    row = (
        await fresh_session.execute(select(Action).where(Action.idempotency_key == key))
    ).scalar_one()
    assert row.state == "awaiting_approval"
