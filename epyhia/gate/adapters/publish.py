from decimal import Decimal

import httpx

from epyhia.gate.errors import VerificationFailed
from epyhia.gate.registry import GateContext, register
from epyhia.ingest.hashing import content_sha256


class PublishFailed(Exception):
    """`execute()` could not put the post in the world. The gate marks the action failed and
    no verification runs (contracts/action-gate.md §7)."""


class PublishAdapter:
    action_type = "publish"
    # A stand-in channel still gets a real approval (FR-043, §4.1): the control is on the
    # decision to put something in front of an audience, not on which API happens to answer.
    requires_approval = True
    # The sink is this application's own endpoint (research.md R4) — it bills nothing.
    cost_usd = Decimal("0")

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self, token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            transport=self._transport,
            timeout=30.0,
        )

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        """A real HTTP round trip to the sink's configured base URL — never an in-process
        call, even though the sink runs in the `web` process. An adapter that reached the
        sink through a function call would make `execute()` and `verify()` two halves of one
        transaction, which is the "status field is not evidence" failure in miniature (R4).
        """
        base = ctx.credentials.require("sink_base_url")
        token = ctx.credentials.require("sink")

        async with self._client(token) as client:
            response = await client.post(f"{base.rstrip('/')}/posts", json=request["payload"])

        if response.status_code >= 400:
            raise PublishFailed(f"publish: {response.status_code} {response.text}")

        body = response.json()
        return {"post_id": body["id"], "permalink": body["permalink"]}

    async def verify(self, request: dict, result: dict, ctx: GateContext) -> dict:
        """Fetch the permalink and assert the sink is holding this payload and no other.

        The hash is recomputed from the request, so what the sink returns has to agree with
        what was asked for — reading the post back and trusting its own report of itself
        would prove only that a row exists.
        """
        token = ctx.credentials.require("sink")
        permalink = result.get("permalink")
        if not permalink:
            # A publish resumed after a crash has no permalink to probe (§7.4). Nothing here
            # can prove it happened, so it lands `failed` rather than being waved through.
            raise VerificationFailed("no permalink to fetch")

        expected = content_sha256(request["payload"])

        async with self._client(token) as client:
            response = await client.get(permalink)

        if response.status_code != 200:
            raise VerificationFailed(f"{permalink} returned {response.status_code}")

        body = response.json()
        if body.get("payload_sha256") != expected:
            raise VerificationFailed(
                f"{permalink} holds {body.get('payload_sha256')!r}, expected {expected!r}"
            )

        return {"post_id": body["id"], "permalink": permalink, "payload_sha256": expected}


register(PublishAdapter())
