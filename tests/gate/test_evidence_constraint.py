import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.actions import Action


async def test_succeeded_with_null_evidence_is_rejected_by_the_database(
    gate_session: AsyncSession,
) -> None:
    action = Action(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        requested_by="marketer",
        action_type="test_evidence_constraint",
        idempotency_key=str(uuid.uuid4()),
        request={},
        state="succeeded",
        evidence=None,
    )
    gate_session.add(action)

    with pytest.raises(IntegrityError, match="ck_actions_succeeded_evidence"):
        await gate_session.commit()
