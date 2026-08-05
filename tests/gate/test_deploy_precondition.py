import uuid

import pytest
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.gate.errors import PreconditionFailed
from epyhia.gate.keys import alias_for, deploy_key

# No agent is imported here, and none can be: the refusal belongs to the gate, so it is
# reachable with zero agents, zero credentials beyond the one being checked, and zero network
# (FR-016, §3.4). A control that lived in the Web Builder would not be testable this way.
BRIEF_HASH = "beef" + "0" * 60

REQUEST = {
    "files": [{"file": "index.html", "data": "<!doctype html><html><head></head></html>"}],
    "brief_hash": BRIEF_HASH,
    "brand_doc_version": 1,
    "prompt_version": "v1",
}


@pytest.fixture(autouse=True)
def _vercel_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The credential check runs ahead of the artifact check, so it has to pass for the
    artifact precondition to be the thing under test."""
    monkeypatch.setattr(settings, "vercel_token", "test-token")


async def _seed_run(session: AsyncSession, grounding_status: str) -> uuid.UUID:
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
            "VALUES (:id, :run_id, 'site', 'index.html', 'text/html', :bytes, :sha, "
            ":status, :violations, 0)"
        ),
        {
            "id": uuid.uuid4(),
            "run_id": run_id,
            "bytes": b"<html></html>",
            "sha": "0" * 64,
            "status": grounding_status,
            "violations": '[{"value": "1", "currency": null}]'
            if grounding_status == "flagged"
            else None,
        },
    )
    await session.commit()
    return run_id


async def _request_deploy(session: AsyncSession, run_id: uuid.UUID) -> dict:
    return await gate.request(
        session,
        run_id=run_id,
        requested_by="web_builder",
        action_type="deploy",
        action_request=REQUEST,
        idempotency_key=deploy_key(BRIEF_HASH, 1, "v1"),
    )


async def test_a_flagged_site_artifact_is_refused_by_the_gate(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("deploy", requires_approval=True)
    registry.register(adapter)
    run_id = await _seed_run(gate_session, "flagged")

    with pytest.raises(PreconditionFailed) as raised:
        await _request_deploy(gate_session, run_id)

    assert raised.value.reason == "site artifact is not clean"

    # Nothing was executed, and nothing was even offered to an operator: the refusal happens
    # in step 1, before any row is written (contracts/action-gate.md §2, §5).
    assert adapter.execute_calls == []
    assert adapter.verify_calls == []
    written = (
        await gate_session.execute(
            text("SELECT count(*) FROM actions WHERE run_id = :run_id"), {"run_id": run_id}
        )
    ).scalar_one()
    assert written == 0


async def test_a_clean_site_artifact_reaches_the_approval_step(
    gate_session: AsyncSession,
) -> None:
    """The mirror, so the refusal above is read as being about the artifact's status rather
    than about `deploy` never getting through at all."""
    adapter = FakeAdapter("deploy", requires_approval=True)
    registry.register(adapter)
    run_id = await _seed_run(gate_session, "clean")

    with pytest.raises(ApprovalRequired):
        await _request_deploy(gate_session, run_id)

    assert adapter.execute_calls == []
    state = (
        await gate_session.execute(
            text("SELECT state FROM actions WHERE run_id = :run_id"), {"run_id": run_id}
        )
    ).scalar_one()
    assert state == "awaiting_approval"
