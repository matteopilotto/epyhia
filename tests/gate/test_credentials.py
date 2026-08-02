import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import CredentialNotConfigured
from epyhia.gate import gate


async def test_missing_credential_names_the_provider_with_no_adapter_registered(
    gate_session: AsyncSession,
) -> None:
    # No adapter registered for "deploy" at all — the precondition must still fail cleanly,
    # never a KeyError from an adapter lookup that never happens.
    with pytest.raises(CredentialNotConfigured) as exc_info:
        await gate.request(
            gate_session,
            run_id=uuid.uuid4(),
            requested_by="web_builder",
            action_type="deploy",
            action_request={},
            idempotency_key=str(uuid.uuid4()),
        )

    assert str(exc_info.value) == "credential not configured: vercel"
