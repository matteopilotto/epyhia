import asyncio
import smtplib
from email.message import EmailMessage

import httpx

from epyhia.gate.errors import VerificationFailed
from epyhia.gate.keys import send_email_key
from epyhia.gate.registry import GateContext, register

DEFAULT_SMTP_PORT = 25

# EPYHIA infrastructure, not client data — and a domain RFC 2606 reserves, so a stand-in
# send can never leave for a real inbox even if a host were misconfigured.
SENDER_DOMAIN = "epyhia.invalid"
SENDER = f"launch@{SENDER_DOMAIN}"

# The catcher holds one local run's traffic, so a single page is enough to find a message
# by its id.
MESSAGE_PAGE_SIZE = 200


class SendFailed(Exception):
    """`execute()` could not hand the message to SMTP. The gate marks the action failed and
    no verification runs (contracts/action-gate.md §7)."""


def message_id_for(request: dict) -> str:
    """The RFC 5322 Message-ID, without its angle brackets, computed from the request the
    same way on both halves of the pair — so `verify()` looks for exactly what `execute()`
    sent rather than trusting what `execute()` returned (§4.5).

    It is the action's idempotency key: a resumed action after a crash then finds the
    message the crashed attempt already sent, instead of sending a second one (§7.4).
    """
    key = send_email_key(request["brief_hash"], request["template"], request["recipient"])
    return f"{key}@{SENDER_DOMAIN}"


class EmailAdapter:
    action_type = "send_email"
    # Anything outbound to a person is one of the three things a human decides (FR-037, §4.4).
    requires_approval = True

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        host = ctx.credentials.require("smtp")
        # Asked for here, not in verify(): an action that cannot be proved must fail before
        # it reaches a person, not after (FR-064, §4.5).
        ctx.credentials.require("mailpit")
        port = int(ctx.credentials.smtp_port or DEFAULT_SMTP_PORT)

        message = EmailMessage()
        message["Message-ID"] = f"<{message_id_for(request)}>"
        message["From"] = SENDER
        message["To"] = request["recipient"]
        message["Subject"] = request["subject"]
        message.set_content(request["body"])

        try:
            await asyncio.to_thread(self._send, host, port, message)
        except (OSError, smtplib.SMTPException) as exc:
            raise SendFailed(f"smtp {host}:{port}: {exc}") from exc

        return {"message_id": message_id_for(request), "recipient": request["recipient"]}

    @staticmethod
    def _send(host: str, port: int, message: EmailMessage) -> None:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.send_message(message)

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        """Read the message back out of the catcher's own API (§4.5).

        The recipient and subject stored as evidence are the ones the catcher holds, not the
        ones the request asked for — a `verify()` that echoes its own input proves nothing
        (contracts/action-gate.md §3).
        """
        api = ctx.credentials.require("mailpit")
        expected = message_id_for(request)

        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.get(
                f"{api.rstrip('/')}/api/v1/messages", params={"limit": MESSAGE_PAGE_SIZE}
            )

        if response.status_code != 200:
            raise VerificationFailed(f"mailpit returned {response.status_code}")

        for message in response.json().get("messages", []):
            # Mailpit stores the header stripped of its angle brackets; strip on the way in
            # too so the comparison does not turn on that detail.
            if (message.get("MessageID") or "").strip("<>") != expected:
                continue
            return {
                "message_id": expected,
                "recipient": ", ".join(
                    to["Address"] for to in message.get("To") or [] if to.get("Address")
                ),
                "subject": message.get("Subject"),
            }

        raise VerificationFailed(f"mailpit holds no message {expected}")


register(EmailAdapter())
