import asyncio
import email
import socket
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.errors import register_exception_handlers
from epyhia.api.routers import sink
from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.email import EmailAdapter, message_id_for
from epyhia.gate.adapters.publish import PublishAdapter
from epyhia.gate.keys import alias_for, send_email_key
from epyhia.ingest.hashing import content_sha256
from epyhia.models.actions import Action

BRIEF_HASH = "5e4d" + "0" * 60

SINK_TOKEN = "test-sink-token"

# EPYHIA-side test values: an outbound address on a reserved domain and a post body with no
# client meaning. Nothing here is read by an assertion about a client (Principle I).
EMAIL_REQUEST = {
    "brief_hash": BRIEF_HASH,
    "template": "launch",
    "recipient": "operator@epyhia.invalid",
    "subject": "A subject",
    "body": "A body.",
}
POST_PAYLOAD = {"channel": "sink", "body": "A post."}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class SmtpCatcher:
    """A real SMTP dialogue on a real socket, so `execute()` genuinely hands the message to a
    server rather than to a mock of one. What `verify()` then reads back is built from what
    this caught — if nothing was sent, verification finds nothing (§4.5)."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        async def reply(line: str) -> None:
            writer.write(line.encode() + b"\r\n")
            await writer.drain()

        await reply("220 epyhia-test ESMTP")
        while line := await reader.readline():
            command = line.decode().strip().upper()
            if command.startswith("DATA"):
                await reply("354 end data with <CR><LF>.<CR><LF>")
                body: list[str] = []
                while data_line := await reader.readline():
                    if data_line.rstrip(b"\r\n") == b".":
                        break
                    body.append(data_line.decode())
                self.messages.append("".join(body))
                await reply("250 queued")
            elif command.startswith("QUIT"):
                await reply("221 bye")
                break
            else:
                await reply("250 ok")
        writer.close()


def _mailpit_transport(catcher: SmtpCatcher) -> httpx.MockTransport:
    """The catcher's API, in the shape Mailpit answers `GET /api/v1/messages` with."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/messages"
        messages = []
        for raw in catcher.messages:
            parsed = email.message_from_string(raw)
            messages.append(
                {
                    "MessageID": (parsed["Message-ID"] or "").strip("<>"),
                    "To": [{"Address": parsed["To"]}],
                    "Subject": parsed["Subject"],
                }
            )
        return httpx.Response(200, json={"messages": messages})

    return httpx.MockTransport(handler)


@pytest_asyncio.fixture
async def smtp_catcher(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SmtpCatcher]:
    catcher = SmtpCatcher()
    port = _free_port()
    server = await asyncio.start_server(catcher._handle, "127.0.0.1", port)
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", str(port))
    monkeypatch.setattr(settings, "mailpit_api_url", "http://catcher.invalid")
    try:
        yield catcher
    finally:
        server.close()
        await server.wait_closed()


@pytest_asyncio.fixture
async def sink_server(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """The recording sink on a real port. The publish adapter reaches it over HTTP exactly as
    it would reach a social API — an in-process call would make `execute()` and `verify()`
    two halves of one transaction (research.md R4)."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(sink.router)

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    base = f"http://127.0.0.1:{port}/sink"
    monkeypatch.setattr(settings, "sink_base_url", base)
    monkeypatch.setattr(settings, "sink_token", SINK_TOKEN)
    try:
        yield base
    finally:
        server.should_exit = True
        await serving


async def _open_run(session: AsyncSession) -> uuid.UUID:
    await session.execute(text("TRUNCATE sink_posts"))
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
    await session.commit()
    return run_id


async def _await_approval(
    session: AsyncSession, run_id: uuid.UUID, *, action_type: str, request: dict, key: str
) -> Action:
    """Every outbound action halts for a human — including publish, whose destination is a
    stand-in. A stand-in channel still gets a real approval (FR-043, §4.1)."""
    with pytest.raises(ApprovalRequired):
        await gate.request(
            session,
            run_id=run_id,
            requested_by="marketer",
            action_type=action_type,
            action_request=request,
            idempotency_key=key,
        )
    action = (
        await session.execute(
            text("SELECT id FROM actions WHERE run_id = :run_id AND action_type = :type"),
            {"run_id": run_id, "type": action_type},
        )
    ).scalar_one()
    parked = await session.get(Action, action)
    assert parked.state == "awaiting_approval"
    assert parked.evidence is None
    return parked


async def test_send_email_halts_then_is_proved_from_the_catcher(
    integration_session: AsyncSession, smtp_catcher: SmtpCatcher
) -> None:
    registry.register(EmailAdapter(transport=_mailpit_transport(smtp_catcher)))
    run_id = await _open_run(integration_session)

    action = await _await_approval(
        integration_session,
        run_id,
        action_type="send_email",
        request=EMAIL_REQUEST,
        key=send_email_key(
            BRIEF_HASH, EMAIL_REQUEST["template"], EMAIL_REQUEST["recipient"]
        ),
    )
    # Nothing reached a person while the decision was outstanding.
    assert smtp_catcher.messages == []

    result = await gate.approve(integration_session, action.id, "auth0|operator")

    assert result["state"] == "succeeded"
    assert len(smtp_catcher.messages) == 1
    # The evidence is what the catcher holds, read back out of its API — not an echo of the
    # request the gate was handed (§4.5).
    assert result["evidence"] == {
        "message_id": message_id_for(EMAIL_REQUEST),
        "recipient": EMAIL_REQUEST["recipient"],
        "subject": EMAIL_REQUEST["subject"],
    }


async def test_send_email_that_never_left_is_never_succeeded(
    integration_session: AsyncSession, smtp_catcher: SmtpCatcher
) -> None:
    """The other half of the same assertion: with the catcher holding nothing, verification
    cannot pass, and the action lands `failed` rather than `succeeded` (FR-041, SC-002)."""
    empty = SmtpCatcher()
    adapter = EmailAdapter(transport=_mailpit_transport(empty))
    registry.register(adapter)
    run_id = await _open_run(integration_session)

    action = await _await_approval(
        integration_session,
        run_id,
        action_type="send_email",
        request=EMAIL_REQUEST,
        key=send_email_key(
            BRIEF_HASH, EMAIL_REQUEST["template"], EMAIL_REQUEST["recipient"]
        ),
    )
    result = await gate.approve(integration_session, action.id, "auth0|operator")

    assert result["state"] == "failed"
    assert result["evidence"] is None
    assert smtp_catcher.messages  # it was sent; the catcher that was probed just has no record


async def test_publish_halts_then_is_proved_from_the_permalink(
    integration_session: AsyncSession, sink_server: str
) -> None:
    registry.register(PublishAdapter())
    run_id = await _open_run(integration_session)

    request = {"payload": POST_PAYLOAD}
    action = await _await_approval(
        integration_session,
        run_id,
        action_type="publish",
        request=request,
        key=content_sha256({"action": "publish", "brief_hash": BRIEF_HASH} | POST_PAYLOAD),
    )
    stored = (
        await integration_session.execute(text("SELECT count(*) FROM sink_posts"))
    ).scalar_one()
    assert stored == 0

    result = await gate.approve(integration_session, action.id, "auth0|operator")

    assert result["state"] == "succeeded"
    evidence = result["evidence"]
    assert evidence["payload_sha256"] == content_sha256(POST_PAYLOAD)
    assert evidence["permalink"].startswith(sink_server)

    # Readable from the permalink by anything holding the token, not only by the adapter.
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {SINK_TOKEN}"}) as client:
        response = await client.get(evidence["permalink"])
    assert response.status_code == 200
    assert response.json()["payload"] == POST_PAYLOAD
