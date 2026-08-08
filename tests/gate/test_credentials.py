import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import CredentialNotConfigured, settings
from epyhia.gate import gate


async def test_missing_credential_names_the_provider_with_no_adapter_registered(
    gate_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The absent credential is arranged, never inherited: this passed for as long as nobody
    # had a token in their `.env`, and went red the moment somebody did. CI must not need a
    # credential to be missing from the environment it happens to run in.
    monkeypatch.setattr(settings, "vercel_token", None)

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
