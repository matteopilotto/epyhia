import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.fake import FakeAdapter
from epyhia.gate.adapters.publish import PublishAdapter
from epyhia.ingest.hashing import content_sha256
from epyhia.models.actions import Action


async def _row_at_verifying(
    session: AsyncSession, action_type: str, result: dict | None
) -> Action:
    """The shape a crash leaves behind once `_run` persists `execute()`'s return: the state
    and the result landed in one commit, so `verifying` without a result only exists for
    rows that predate the `actions.result` column."""
    action = Action(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        requested_by="marketer",
        action_type=action_type,
        idempotency_key=str(uuid.uuid4()),
        request={"marker": "re-driven"},
        state="verifying",
        result=result,
    )
    session.add(action)
    await session.commit()
    return action


async def test_execute_result_is_durable_even_when_verify_burns_out(
    gate_session: AsyncSession,
) -> None:
    """The result lands in the same commit as `verifying`, so it is on the row before the
    first probe — which is what makes a `failed` action re-verifiable at all (T146)."""
    adapter = FakeAdapter("test_result_durable", always_fail_verify=True)
    registry.register(adapter)

    result = await gate.request(
        gate_session,
        run_id=uuid.uuid4(),
        requested_by="ops",
        action_type=adapter.action_type,
        action_request={},
        idempotency_key=str(uuid.uuid4()),
    )

    assert result["state"] == "failed"
    action = await gate_session.get(Action, result["action_id"])
    assert action.result == {"ok": True}


async def test_a_re_driven_action_verifies_from_the_stored_result(
    gate_session: AsyncSession,
) -> None:
    adapter = FakeAdapter("test_result_redrive")
    registry.register(adapter)
    action = await _row_at_verifying(
        gate_session, adapter.action_type, {"handle": "stored-by-execute"}
    )

    result = await gate.resume(gate_session, action.id)

    assert result["state"] == "succeeded"
    assert adapter.verify_results == [{"handle": "stored-by-execute"}]


async def test_an_observer_passed_result_wins_over_the_store(
    gate_session: AsyncSession,
) -> None:
    """`resume(result=...)` is what an observer saw — for a deferred verification, the
    handle the provider's callback carried — and it outranks execute()'s stored word."""
    adapter = FakeAdapter("test_result_observer")
    registry.register(adapter)
    action = await _row_at_verifying(
        gate_session, adapter.action_type, {"handle": "stored-by-execute"}
    )

    result = await gate.resume(gate_session, action.id, result={"handle": "observed"})

    assert result["state"] == "succeeded"
    assert adapter.verify_results == [{"handle": "observed"}]


async def test_a_deferred_verification_persists_the_handle_it_parks_on(
    gate_session: AsyncSession,
) -> None:
    """A checkout session's handle is exactly what the webhook needs re-findable — the row
    stays `verifying` and the result must survive the process that requested it."""
    adapter = FakeAdapter("test_result_deferred")
    adapter.defer_verification = True
    registry.register(adapter)

    result = await gate.request(
        gate_session,
        run_id=uuid.uuid4(),
        requested_by="ops",
        action_type=adapter.action_type,
        action_request={},
        idempotency_key=str(uuid.uuid4()),
    )

    assert result["state"] == "verifying"
    action = await gate_session.get(Action, result["action_id"])
    assert action.result == {"ok": True}


PAYLOAD = {"angle": "origin", "body": "A post about origin."}
PERMALINK = "https://sink.invalid/posts/1f0a"


def _sink_transport() -> httpx.MockTransport:
    """A sink holding exactly the post the action published."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == PERMALINK:
            return httpx.Response(
                200,
                json={
                    "id": "1f0a",
                    "payload": PAYLOAD,
                    "payload_sha256": content_sha256(PAYLOAD),
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_a_publish_resumed_after_a_crash_verifies_from_the_stored_permalink(
    gate_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The §7.4 caveat, retired for post-migration rows: a publish that died after
    `execute()` re-drives from the permalink the row now holds, instead of landing
    `failed` on "no permalink to fetch"."""
    monkeypatch.setattr(settings, "sink_token", "test-token")
    registry.register(PublishAdapter(transport=_sink_transport()))
    action = await _row_at_verifying(
        gate_session, "publish", {"post_id": "1f0a", "permalink": PERMALINK}
    )
    action.request = {"payload": PAYLOAD}
    await gate_session.commit()

    result = await gate.resume(gate_session, action.id)

    assert result["state"] == "succeeded"
    assert result["evidence"]["permalink"] == PERMALINK


async def test_a_publish_row_predating_the_result_column_still_lands_failed(
    gate_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `verifying` row with no stored result — only pre-migration rows can be one — still
    has nothing to probe, and lands `failed` rather than being waved through. Those rows
    are healed by `scripts/backfill_action_results.py`, not by guessing here."""
    monkeypatch.setattr(settings, "sink_token", "test-token")
    registry.register(PublishAdapter(transport=_sink_transport()))
    action = await _row_at_verifying(gate_session, "publish", None)
    action.request = {"payload": PAYLOAD}
    await gate_session.commit()

    result = await gate.resume(gate_session, action.id)

    assert result["state"] == "failed"
    assert "no permalink" in result["error"]
