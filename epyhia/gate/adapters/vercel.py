import asyncio
import base64
import re

import httpx

from epyhia.gate.keys import alias_for
from epyhia.gate.registry import GateContext

API_BASE = "https://api.vercel.com"

# One Vercel project per brief, named from the brief hash (R2). "One brief, one URL" is then
# a property of the namespace rather than of bookkeeping, and the alias is derivable from
# the brief hash alone — which is what lets verify() compute the URL it probes.
PROJECT_PREFIX = "epyhia-"

MARKER_NAME = "epyhia-build"
_HEAD_OPEN = re.compile(r"<head[^>]*>", re.IGNORECASE)


class DeployFailed(Exception):
    """`execute()` could not put the files in the world. The gate marks the action failed
    and no verification runs (contracts/action-gate.md §7)."""


def build_marker(request: dict) -> str:
    """`<brief_hash[:8]>.<brand_doc_version>.<prompt_version>` — computed by the adapter,
    deterministically, from the request. Both halves of the pair derive it the same way, so
    what `verify()` looks for is exactly what `execute()` put there (R3)."""
    return (
        f"{request['brief_hash'][:8]}"
        f".{request['brand_doc_version']}"
        f".{request['prompt_version']}"
    )


def inject_marker(html: str, marker: str) -> str:
    """Insert the build marker into `<head>` **on the wire**, not into the stored artifact.

    The memoisation cache is keyed on the artifact's inputs and its `sha256` is a dedup key,
    so a generated marker would change the artifact hash every time the brand doc was edited
    — for a reason unrelated to the page's content. Injecting here keeps the artifact a pure
    function of the brief and brand doc, and keeps the difference auditable (R3, FR-019).
    """
    match = _HEAD_OPEN.search(html)
    if match is None:
        raise DeployFailed("site markup has no <head> to carry the build marker")
    tag = f'<meta name="{MARKER_NAME}" content="{marker}">'
    return html[: match.end()] + tag + html[match.end() :]


class VercelAdapter:
    action_type = "deploy"
    # Going live is one of the three things a human decides (FR-037, §4.4).
    requires_approval = True

    poll_interval_seconds = 1.0
    max_poll_attempts = 60

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self, token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {token}"},
            transport=self._transport,
            timeout=30.0,
        )

    async def execute(self, request: dict, ctx: GateContext) -> dict:
        token = ctx.credentials.require("vercel")
        brief_hash = request["brief_hash"]
        project = f"{PROJECT_PREFIX}{brief_hash[:12]}"

        async with self._client(token) as client:
            deployment = await self._create_deployment(client, project, request)
            deployment_id = deployment["id"]
            ready = await self._poll_until_ready(client, deployment_id)
            await self._assign_alias(client, deployment_id, alias_for(brief_hash))

        return {
            "deployment_id": deployment_id,
            "project": project,
            "readyState": ready,
            # Recorded, but never what verify() probes: the alias is derived, not returned.
            "url": deployment.get("url"),
        }

    async def _create_deployment(
        self, client: httpx.AsyncClient, project: str, request: dict
    ) -> dict:
        marker = build_marker(request)
        files = []
        for item in request["files"]:
            data = item["data"]
            if item["file"].lower().endswith(".html"):
                data = inject_marker(data, marker)
            files.append(
                {
                    "file": item["file"],
                    "data": base64.b64encode(data.encode("utf-8")).decode("ascii"),
                    "encoding": "base64",
                }
            )
        response = await client.post(
            "/v13/deployments",
            json={
                "name": project,
                "files": files,
                "target": "production",
                # A hand-authored single page: nothing to build, and no Node in the gate's
                # execution path (R2, §6.1).
                "projectSettings": {
                    "framework": None,
                    "buildCommand": None,
                    "outputDirectory": ".",
                },
            },
        )
        if response.status_code >= 400:
            raise DeployFailed(f"create deployment: {response.status_code} {response.text}")
        return response.json()

    async def _poll_until_ready(self, client: httpx.AsyncClient, deployment_id: str) -> str:
        for attempt in range(self.max_poll_attempts):
            response = await client.get(f"/v13/deployments/{deployment_id}")
            if response.status_code >= 400:
                raise DeployFailed(f"poll: {response.status_code} {response.text}")
            state = response.json().get("readyState")
            if state == "READY":
                return state
            if state == "ERROR":
                raise DeployFailed(f"deployment {deployment_id} reached readyState ERROR")
            if attempt + 1 < self.max_poll_attempts:
                await asyncio.sleep(self.poll_interval_seconds)
        raise DeployFailed(f"deployment {deployment_id} never reached READY")

    async def _assign_alias(
        self, client: httpx.AsyncClient, deployment_id: str, alias: str
    ) -> None:
        """Kept as its own observable step even though a production deploy to a per-brief
        project would land on the same host anyway: "the deployment succeeded but the alias
        still serves the previous build" is the failure §4.5's second assertion exists for,
        and it stays detectable only while the switch is a step of its own (R2)."""
        response = await client.post(
            f"/v2/deployments/{deployment_id}/aliases", json={"alias": alias}
        )
        # 409 means the alias is already assigned to this deployment — success, not an error.
        if response.status_code >= 400 and response.status_code != 409:
            raise DeployFailed(f"assign alias: {response.status_code} {response.text}")
