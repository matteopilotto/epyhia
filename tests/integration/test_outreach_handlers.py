import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import marketer
from epyhia.artifacts.store import PostgresArtifactStore
from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.email import EmailAdapter, message_id_for
from epyhia.gate.adapters.publish import PublishAdapter
from epyhia.gate.keys import alias_for, publish_key, send_email_key
from epyhia.ingest.hashing import content_sha256
from epyhia.models.actions import Action
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import run_once
from tests.integration.test_demand_pack import load_brief
from tests.integration.test_us2_send_verify import (  # noqa: F401  — pulled in as a fixture
    _mailpit_transport,
    smtp_catcher,
)

_store = PostgresArtifactStore()

SINK_BASE_URL = "https://sink.invalid"


class FakeSink:
    """A stand-in sink reached over real HTTP semantics via `httpx.MockTransport`, so
    `execute()` and `verify()` stay two genuinely separate round trips (research.md R4) —
    without the real sink app's own `uvicorn` process and its `get_session` dependency,
    which caches its database engine per event loop (`epyhia/api/db.py`) and collides with
    `test_us2_send_verify.py`'s own live sink server when both run in the same session."""

    def __init__(self) -> None:
        self._posts: dict[str, dict] = {}

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/posts":
                payload = json.loads(request.content)
                post_id = str(uuid.uuid4())
                permalink = f"{SINK_BASE_URL}/posts/{post_id}"
                self._posts[permalink] = {
                    "id": post_id,
                    "payload": payload,
                    "payload_sha256": content_sha256(payload),
                }
                return httpx.Response(201, json={"id": post_id, "permalink": permalink})
            if request.method == "GET":
                stored = self._posts.get(str(request.url))
                if stored is None:
                    return httpx.Response(404)
                return httpx.Response(200, json=stored)
            return httpx.Response(404)

        return httpx.MockTransport(handler)

BRAND_DOC_VERSION = 1
BRAND_DOC = {
    "name": "Meridian Coffee Roasters",
    "descriptor": "A neighbourhood roastery.",
    "palette": {"bg": "#101014", "fg": "#f4f4f5", "accent": "#c2410c", "muted": "#71717a"},
    "type": {"display": "Display Face", "body": "Body Face"},
}

POSTS = [
    {"angle": "origin", "body": "A post about origin."},
    {"angle": "roast", "body": "A post about roast."},
    {"angle": "shipping", "body": "A post about shipping."},
]
EMAIL = {"subject": "We're live", "preheader": "It's here", "body": "Read all about it."}


async def _open_run(session: AsyncSession, brief_payload: dict) -> tuple[Run, str]:
    brief_hash = content_sha256(brief_payload)
    brief = Brief(
        id=uuid.uuid4(),
        payload=brief_payload,
        content_sha256=brief_hash,
        guardrail_decision="pass",
        guardrail_reason="fixture brief, screened offline",
        guardrail_model="test-model",
    )
    session.add(brief)
    await session.flush()
    brand_doc = BrandDoc(
        id=uuid.uuid4(),
        brief_id=brief.id,
        version=BRAND_DOC_VERSION,
        doc=BRAND_DOC,
        authored_by="strategist",
    )
    session.add(brand_doc)
    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        brand_doc_id=brand_doc.id,
        prompt_version="v1",
        grounding_set={"literal": [], "derived": []},
        budget_usd=25,
        status="running",
        alias=alias_for(brief_hash),
    )
    session.add(run)
    await session.flush()
    await session.commit()
    return run, brief_hash


async def _seed_posts(
    session: AsyncSession,
    run_id: uuid.UUID,
    posts: list[dict],
    *,
    grounding_status: str = "clean",
) -> None:
    await _store.write(
        session,
        run_id=run_id,
        kind="posts",
        path="posts.json",
        content_type="application/json",
        content=json.dumps({"posts": posts}).encode("utf-8"),
        grounding_status=grounding_status,
    )
    await session.commit()


async def _seed_email(
    session: AsyncSession, run_id: uuid.UUID, email: dict, *, grounding_status: str = "clean"
) -> None:
    await _store.write(
        session,
        run_id=run_id,
        kind="email",
        path="email.json",
        content_type="application/json",
        content=json.dumps(email).encode("utf-8"),
        grounding_status=grounding_status,
    )
    await session.commit()


async def _resume(session: AsyncSession, action_id: uuid.UUID) -> Action:
    """The park→approve→resume cycle every gated action goes through, exactly as
    `tests/integration/test_us1_brief_to_site.py::test_brief_becomes_a_proved_live_site_once_approved`
    drives it: the decision is written durably first, and a `resume` task carries it to its
    outcome — which is also what settles the original parked task `done`."""
    await gate.record_approval(session, action_id, "auth0|operator")
    session.add(
        Task(
            id=uuid.uuid4(),
            run_id=(await session.get(Action, action_id)).run_id,
            kind="resume",
            state="pending",
            payload={"action_id": str(action_id)},
        )
    )
    await session.commit()
    assert await run_once(session, kind="resume")
    return await session.get(Action, action_id)


async def test_publish_parks_then_resumes_to_a_stored_sink_post(
    integration_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sink_base_url", SINK_BASE_URL)
    monkeypatch.setattr(settings, "sink_token", "test-sink-token")
    registry.register(PublishAdapter(transport=FakeSink().transport()))
    run, brief_hash = await _open_run(integration_session, load_brief())
    run_id = run.id
    await _seed_posts(integration_session, run_id, POSTS)
    task = Task(
        id=uuid.uuid4(), run_id=run_id, kind="publish", state="pending", payload={"slot": 1}
    )
    integration_session.add(task)
    await integration_session.commit()

    assert await run_once(integration_session, kind="publish")
    await integration_session.refresh(task)
    assert task.state == "awaiting_approval"
    action_id = uuid.UUID(task.payload["action_id"])

    action = await integration_session.get(Action, action_id)
    assert action.state == "awaiting_approval"
    assert action.idempotency_key == publish_key(
        brief_hash, BRAND_DOC_VERSION, marketer.PROMPT_VERSION, 1
    )
    assert action.request == {"payload": POSTS[1], "brief_hash": brief_hash}

    action = await _resume(integration_session, action_id)
    assert action.state == "succeeded"
    # Proof it landed is what `verify()` itself read back from the sink's own API — a second,
    # independent round trip through the same fake transport (research.md R4).
    assert action.evidence["payload_sha256"] == content_sha256(POSTS[1])
    assert action.evidence["permalink"].startswith(SINK_BASE_URL)

    await integration_session.refresh(task)
    assert task.state == "done"


async def test_publish_refuses_a_flagged_posts_artifact_named_and_writes_no_action(
    integration_session: AsyncSession,
) -> None:
    registry.register(PublishAdapter())
    run, _ = await _open_run(integration_session, load_brief())
    run_id = run.id
    await _seed_posts(integration_session, run_id, POSTS, grounding_status="flagged")
    task = Task(
        id=uuid.uuid4(), run_id=run_id, kind="publish", state="pending", payload={"slot": 0}
    )
    integration_session.add(task)
    await integration_session.commit()

    assert await run_once(integration_session, kind="publish")
    await integration_session.refresh(task)
    assert task.state == "failed"
    assert "not clean" in task.error

    count = await integration_session.scalar(
        select(func.count()).select_from(Action).where(Action.run_id == run_id)
    )
    assert count == 0


async def test_publish_refuses_a_slot_beyond_a_reduced_regeneration(
    integration_session: AsyncSession,
) -> None:
    """`slot` is fixed at enqueue time; a re-generated posts artifact may hold fewer posts
    than it once did, and that has to fail by name rather than publish the wrong slot."""
    registry.register(PublishAdapter())
    run, _ = await _open_run(integration_session, load_brief())
    run_id = run.id
    await _seed_posts(integration_session, run_id, POSTS[:1])
    task = Task(
        id=uuid.uuid4(), run_id=run_id, kind="publish", state="pending", payload={"slot": 2}
    )
    integration_session.add(task)
    await integration_session.commit()

    assert await run_once(integration_session, kind="publish")
    await integration_session.refresh(task)
    assert task.state == "failed"
    assert "slot 2 of a 1-post artifact" in task.error


async def test_send_email_parks_then_resumes_to_a_sent_message(
    integration_session: AsyncSession, smtp_catcher  # noqa: F811
) -> None:
    registry.register(EmailAdapter(transport=_mailpit_transport(smtp_catcher)))
    brief_payload = load_brief()
    run, brief_hash = await _open_run(integration_session, brief_payload)
    await _seed_email(integration_session, run.id, EMAIL)
    task = Task(id=uuid.uuid4(), run_id=run.id, kind="send_email", state="pending")
    integration_session.add(task)
    await integration_session.commit()

    assert await run_once(integration_session, kind="send_email")
    await integration_session.refresh(task)
    assert task.state == "awaiting_approval"
    action_id = uuid.UUID(task.payload["action_id"])

    recipient = brief_payload["contact"]["email"]
    action = await integration_session.get(Action, action_id)
    assert action.request == {
        "brief_hash": brief_hash,
        "template": "launch",
        "recipient": recipient,
        "subject": EMAIL["subject"],
        "body": EMAIL["body"],
    }
    assert action.idempotency_key == send_email_key(brief_hash, "launch", recipient)

    action = await _resume(integration_session, action_id)
    assert action.state == "succeeded"
    assert action.evidence == {
        "message_id": message_id_for(action.request),
        "recipient": recipient,
        "subject": EMAIL["subject"],
    }

    await integration_session.refresh(task)
    assert task.state == "done"


async def test_send_email_refuses_a_missing_contact_email_named_and_writes_no_action(
    integration_session: AsyncSession,
) -> None:
    registry.register(EmailAdapter())
    brief_payload = load_brief()
    del brief_payload["contact"]["email"]
    run, _ = await _open_run(integration_session, brief_payload)
    run_id = run.id
    await _seed_email(integration_session, run_id, EMAIL)
    task = Task(id=uuid.uuid4(), run_id=run_id, kind="send_email", state="pending")
    integration_session.add(task)
    await integration_session.commit()

    assert await run_once(integration_session, kind="send_email")
    await integration_session.refresh(task)
    assert task.state == "failed"
    assert "no contact.email" in task.error

    count = await integration_session.scalar(
        select(func.count()).select_from(Action).where(Action.run_id == run_id)
    )
    assert count == 0


async def test_send_email_refuses_a_flagged_email_artifact_named(
    integration_session: AsyncSession,
) -> None:
    registry.register(EmailAdapter())
    run, _ = await _open_run(integration_session, load_brief())
    run_id = run.id
    await _seed_email(integration_session, run_id, EMAIL, grounding_status="flagged")
    task = Task(id=uuid.uuid4(), run_id=run_id, kind="send_email", state="pending")
    integration_session.add(task)
    await integration_session.commit()

    assert await run_once(integration_session, kind="send_email")
    await integration_session.refresh(task)
    assert task.state == "failed"
    assert "not clean" in task.error
