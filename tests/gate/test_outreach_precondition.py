import uuid

import pytest
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.gate.errors import PreconditionFailed
from epyhia.gate.keys import alias_for, publish_key, send_email_key

# No agent is imported here, and none can be: the refusal belongs to the gate, so it is
# reachable with zero agents, zero credentials beyond the one being checked, and zero
# network (FR-016, §3.4) — the same posture as test_deploy_precondition.py, mirrored for the
# two outreach actions.
BRIEF_HASH = "face" + "0" * 60

PUBLISH_REQUEST = {"payload": {"channel": "sink", "body": "A post."}, "brief_hash": BRIEF_HASH}
EMAIL_REQUEST = {
    "brief_hash": BRIEF_HASH,
    "template": "launch",
    "recipient": "operator@epyhia.invalid",
    "subject": "A subject",
    "body": "A body.",
}


@pytest.fixture(autouse=True)
def _credentials_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The credential check runs ahead of the artifact check, so it has to pass for the
    artifact precondition to be the thing under test (same posture as the deploy test)."""
    monkeypatch.setattr(settings, "sink_token", "test-sink-token")
    monkeypatch.setattr(settings, "smtp_host", "test-smtp-host")


async def _seed_run(session: AsyncSession, kind: str, grounding_status: str) -> uuid.UUID:
    await session.execute(
        text(
            "DELETE FROM artifacts WHERE run_id IN "
            "(SELECT r.id FROM runs r JOIN briefs b ON b.id = r.brief_id "
            " WHERE b.content_sha256 = :hash)"
        ),
        {"hash": BRIEF_HASH},
    )
    await session.execute(
        text(
            "DELETE FROM runs WHERE brief_id IN "
            "(SELECT id FROM briefs WHERE content_sha256 = :hash)"
        ),
        {"hash": BRIEF_HASH},
    )
    await session.execute(
        text("DELETE FROM briefs WHERE content_sha256 = :hash"), {"hash": BRIEF_HASH}
    )

    brief_id, run_id = uuid.uuid4(), uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO briefs (id, payload, content_sha256, guardrail_decision, guardrail_model) "
            "VALUES (:id, '{}'::jsonb, :hash, 'pass', 'test-model')"
        ),
        {"id": brief_id, "hash": BRIEF_HASH},
    )
    await session.execute(
        text(
            "INSERT INTO runs (id, brief_id, prompt_version, grounding_set, budget_usd, "
            "spend_usd, status, alias) "
            "VALUES (:id, :brief_id, 'v1', '{}'::jsonb, 25, 0, 'running', :alias)"
        ),
        {"id": run_id, "brief_id": brief_id, "alias": alias_for(BRIEF_HASH)},
    )
    await session.execute(
        text(
            "INSERT INTO artifacts (id, run_id, kind, path, content_type, bytes, sha256, "
            "grounding_status, violations, revision) "
            "VALUES (:id, :run_id, :kind, 'artifact.json', 'application/json', :bytes, :sha, "
            ":status, :violations, 0)"
        ),
        {
            "id": uuid.uuid4(),
            "run_id": run_id,
            "kind": kind,
            "bytes": b"{}",
            "sha": "0" * 64,
            "status": grounding_status,
            "violations": '[{"value": "1", "currency": null}]'
            if grounding_status == "flagged"
            else None,
        },
    )
    await session.commit()
    return run_id


async def test_publish_is_refused_for_a_flagged_posts_artifact(gate_session: AsyncSession) -> None:
    adapter = FakeAdapter("publish", requires_approval=True)
    registry.register(adapter)
    run_id = await _seed_run(gate_session, "posts", "flagged")

    with pytest.raises(PreconditionFailed) as raised:
        await gate.request(
            gate_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="publish",
            action_request=PUBLISH_REQUEST,
            idempotency_key=publish_key(BRIEF_HASH, 1, "v1", 0),
        )

    assert raised.value.reason == "posts artifact is not clean"
    assert adapter.execute_calls == []


async def test_publish_reaches_the_approval_step_for_a_clean_posts_artifact(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("publish", requires_approval=True)
    registry.register(adapter)
    run_id = await _seed_run(gate_session, "posts", "clean")

    with pytest.raises(ApprovalRequired):
        await gate.request(
            gate_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="publish",
            action_request=PUBLISH_REQUEST,
            idempotency_key=publish_key(BRIEF_HASH, 1, "v1", 0),
        )

    assert adapter.execute_calls == []


async def test_send_email_is_refused_for_a_flagged_email_artifact(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("send_email", requires_approval=True)
    registry.register(adapter)
    run_id = await _seed_run(gate_session, "email", "flagged")

    with pytest.raises(PreconditionFailed) as raised:
        await gate.request(
            gate_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="send_email",
            action_request=EMAIL_REQUEST,
            idempotency_key=send_email_key(
                BRIEF_HASH, EMAIL_REQUEST["template"], EMAIL_REQUEST["recipient"]
            ),
        )

    assert raised.value.reason == "email artifact is not clean"
    assert adapter.execute_calls == []


async def test_send_email_reaches_the_approval_step_for_a_clean_email_artifact(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("send_email", requires_approval=True)
    registry.register(adapter)
    run_id = await _seed_run(gate_session, "email", "clean")

    with pytest.raises(ApprovalRequired):
        await gate.request(
            gate_session,
            run_id=run_id,
            requested_by="marketer",
            action_type="send_email",
            action_request=EMAIL_REQUEST,
            idempotency_key=send_email_key(
                BRIEF_HASH, EMAIL_REQUEST["template"], EMAIL_REQUEST["recipient"]
            ),
        )

    assert adapter.execute_calls == []
