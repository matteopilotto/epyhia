import base64
import copy
import json
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.queue.handlers  # noqa: F401  — registers every task handler
from epyhia.agents import marketer, reviewer, strategist, web_builder
from epyhia.api.app import create_app
from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.vercel import VercelAdapter, build_marker
from epyhia.gate.keys import alias_for
from epyhia.models.actions import Action
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import run_once
from tests.integration.test_us1_brief_to_site import (
    _marketer_model,
    _open_run,
    _reviewer_model,
    _strategist_model,
    _web_builder_model,
    load_brief,
)

pytestmark = pytest.mark.asyncio

OPERATOR = "auth0|operator"


class VercelWorld:
    """Vercel's two kinds of URL, which is the whole point of this test.

    Each deployment gets its own immutable host and keeps whatever was uploaded to it,
    forever. The alias is a pointer, moved by `/aliases`. A second publication therefore has
    to leave the first one readable at its own URL while the alias moves on (FR-017).
    """

    def __init__(self, alias: str) -> None:
        # Derived from the run's own brief hash by the caller — never a literal (FR-018).
        self.alias = alias
        self.deployments: dict[str, str] = {}
        self.alias_target: str | None = None

    def host_of(self, deployment_id: str) -> str:
        return f"{deployment_id.replace('_', '-')}.vercel.app"

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.vercel.com":
            return self._api(request)
        host = request.url.host
        if host == self.alias:
            host = self.host_of(self.alias_target) if self.alias_target else host
        served = self.deployments.get(host)
        return httpx.Response(200 if served is not None else 404, text=served or "")

    def _api(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if request.url.path == "/v13/deployments" and request.method == "POST":
            deployment_id = f"dpl_{len(self.deployments) + 1}"
            uploaded = base64.b64decode(body["files"][0]["data"]).decode("utf-8")
            self.deployments[self.host_of(deployment_id)] = uploaded
            return httpx.Response(
                200, json={"id": deployment_id, "url": self.host_of(deployment_id)}
            )
        if request.url.path.startswith("/v13/deployments/"):
            return httpx.Response(200, json={"readyState": "READY"})
        if request.url.path.endswith("/aliases"):
            self.alias_target = request.url.path.split("/")[3]
            return httpx.Response(200, json={})
        return httpx.Response(404)


def client_for(session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_operator] = lambda: {"sub": OPERATOR}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test/api"
    )


async def _approve_pending_deploy(session: AsyncSession, run_id: uuid.UUID) -> Action:
    action = (
        await session.execute(
            select(Action).where(
                Action.run_id == run_id,
                Action.action_type == "deploy",
                Action.state == "awaiting_approval",
            )
        )
    ).scalar_one()
    await gate.record_approval(session, action.id, OPERATOR)
    session.add(
        Task(
            id=uuid.uuid4(),
            run_id=run_id,
            kind="resume",
            state="pending",
            payload={"action_id": str(action.id)},
        )
    )
    await session.commit()
    assert await run_once(session, kind="resume")
    await session.refresh(action)
    assert action.state == "succeeded"
    return action


async def test_an_edited_brand_doc_publishes_a_second_time_without_unpublishing_the_first(
    integration_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing the brand doc and re-running is the case that is *supposed* to fire (§7.2).

    The deploy key is `brief + brand doc version + prompt version`, so a new version is a new
    key and therefore a genuine second publication — two rows in the audit trail with two
    keys, which is exactly what a duplicate is not. And Vercel's per-deployment URL is
    immutable, so the first publication stays readable at its own URL after the alias moves
    (FR-012, FR-017, US1 scenario 5).
    """
    monkeypatch.setattr(settings, "vercel_token", "test-token")

    payload = load_brief()
    run_id, brief_hash = await _open_run(integration_session, payload)

    world = VercelWorld(alias_for(brief_hash))
    adapter = VercelAdapter(transport=httpx.MockTransport(world.handler))
    adapter.poll_interval_seconds = 0
    registry.register(adapter)

    with strategist.agent.override(model=_strategist_model(payload)):
        assert await run_once(integration_session, kind="plan")
    with (
        marketer.agent.override(model=_marketer_model()),
        reviewer.agent.override(model=_reviewer_model()),
    ):
        assert await run_once(integration_session, kind="copy")
    with web_builder.agent.override(model=_web_builder_model()):
        assert await run_once(integration_session, kind="site")

    first = await _approve_pending_deploy(integration_session, run_id)
    first_deployment = world.alias_target
    first_url = f"https://{world.host_of(first_deployment)}"

    run = await integration_session.get(Run, run_id)
    v1 = await integration_session.get(BrandDoc, run.brand_doc_id)
    assert first.evidence["matched_build_marker"] == build_marker(first.request)
    assert first.request["brand_doc_version"] == v1.version

    # The operator edits the brand doc. `PUT` inserts version + 1 and re-points the run.
    edited = copy.deepcopy(v1.doc)
    edited["palette"]["accent"] = "#0ea5e9"
    async with client_for(integration_session) as client:
        response = await client.put(f"/runs/{run_id}/brand-doc", json=edited)
    assert response.status_code == 200
    assert response.json()["version"] == v1.version + 1

    # Re-run the stage. The brand doc version is in the memo key, so this regenerates rather
    # than serving the first build's hit — which is the §5.3 demo's whole requirement.
    integration_session.add(
        Task(id=uuid.uuid4(), run_id=run_id, kind="site", state="pending")
    )
    await integration_session.commit()
    with web_builder.agent.override(model=_web_builder_model()):
        assert await run_once(integration_session, kind="site")

    second = await _approve_pending_deploy(integration_session, run_id)

    # A genuine second publication: two rows, two keys, two approvals. A duplicate would have
    # short-circuited onto the first row and left one.
    deploys = (
        await integration_session.execute(
            select(Action)
            .where(Action.run_id == run_id, Action.action_type == "deploy")
            .order_by(Action.created_at)
        )
    ).scalars().all()
    assert len(deploys) == 2
    assert deploys[0].idempotency_key != deploys[1].idempotency_key
    assert [row.request["brand_doc_version"] for row in deploys] == [
        v1.version,
        v1.version + 1,
    ]
    assert all(row.approval_decision == "approved" for row in deploys)

    # The alias moved: it now serves the second build's marker, not the first's.
    assert second.evidence["matched_build_marker"] == build_marker(second.request)
    assert second.evidence["matched_build_marker"] != first.evidence["matched_build_marker"]
    assert world.alias_target != first_deployment

    # And the first publication is still readable at its own immutable URL, serving the
    # marker it went live with (FR-017).
    async with httpx.AsyncClient(transport=httpx.MockTransport(world.handler)) as client:
        served = await client.get(first_url)
    assert served.status_code == 200
    assert f'content="{first.evidence["matched_build_marker"]}"' in served.text
    assert f'content="{second.evidence["matched_build_marker"]}"' not in served.text
