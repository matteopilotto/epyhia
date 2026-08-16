import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.ingest.hashing import content_sha256
from epyhia.models.actions import Action
from epyhia.models.sink_posts import SinkPost
from scripts.backfill_action_results import backfill

BASE_URL = "https://api.test/api/sink"


async def _failed_publish(session: AsyncSession, payload: dict) -> uuid.UUID:
    """The incident's row shape: `execute()` succeeded, verify burned five attempts on the
    301, and nothing durable held the permalink — `result` is NULL."""
    action_id = uuid.uuid4()
    session.add(
        Action(
            id=action_id,
            run_id=uuid.uuid4(),
            requested_by="marketer",
            action_type="publish",
            idempotency_key=str(uuid.uuid4()),
            request={"payload": payload},
            state="failed",
            error="http://api.test/api/sink/posts/x returned 301",
            verify_attempts=5,
        )
    )
    await session.commit()
    return action_id


async def _sink_post(session: AsyncSession, payload: dict) -> uuid.UUID:
    post_id = uuid.uuid4()
    session.add(
        SinkPost(id=post_id, payload=payload, payload_sha256=content_sha256(payload))
    )
    await session.commit()
    return post_id


async def test_backfill_rebuilds_the_result_from_the_sinks_own_record(
    integration_session: AsyncSession,
) -> None:
    payload = {"angle": "origin", "body": f"A post {uuid.uuid4()}"}
    action_id = await _failed_publish(integration_session, payload)
    post_id = await _sink_post(integration_session, payload)

    results = await backfill(integration_session, BASE_URL)

    assert results == [{"action_id": action_id, "matched": True, "post_id": post_id}]
    action = await integration_session.get(Action, action_id)
    await integration_session.refresh(action)
    assert action.result == {
        "post_id": str(post_id),
        "permalink": f"{BASE_URL}/posts/{post_id}",
    }
    # Re-verification prep only: the state is untouched — the reverify endpoint and its
    # probe decide what the row becomes, not this script.
    assert action.state == "failed"


async def test_a_publish_with_no_sink_match_is_left_alone_and_reported(
    integration_session: AsyncSession,
) -> None:
    """A publish that truly never executed must stay `failed` with nothing to verify from —
    inventing a result here would wave an unproved effect through the T146 guard."""
    payload = {"angle": "roast", "body": f"A post {uuid.uuid4()}"}
    action_id = await _failed_publish(integration_session, payload)

    results = await backfill(integration_session, BASE_URL)

    assert results == [
        {
            "action_id": action_id,
            "matched": False,
            "payload_sha256": content_sha256(payload),
        }
    ]
    action = await integration_session.get(Action, action_id)
    assert action.result is None
    assert action.state == "failed"


async def test_backfill_is_a_no_op_on_a_second_invocation(
    integration_session: AsyncSession,
) -> None:
    payload = {"angle": "shipping", "body": f"A post {uuid.uuid4()}"}
    await _failed_publish(integration_session, payload)
    await _sink_post(integration_session, payload)

    first = await backfill(integration_session, BASE_URL)
    second = await backfill(integration_session, BASE_URL)

    assert len(first) == 1 and first[0]["matched"]
    assert second == []
