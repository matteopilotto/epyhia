import base64
import json
import uuid

import httpx
import pytest
from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.config import settings
from epyhia.gate import gate, registry
from epyhia.gate.adapters.vercel import VercelAdapter, build_marker
from epyhia.gate.errors import VerificationFailed
from epyhia.gate.keys import alias_for
from epyhia.gate.registry import GateContext

BRIEF_HASH = "0123456789ab" + "f" * 52

# Client-blind by construction: the probe string is whatever brand doc the adapter is handed,
# and these tests assert against that same value rather than a literal of their own (FR-059).
BRAND_DOC = {"name": "Placeholder Brand"}

MARKUP = "<!doctype html><html><head></head><body></body></html>"
REQUEST = {
    "files": [{"file": "index.html", "data": MARKUP}],
    "brief_hash": BRIEF_HASH,
    "brand_doc_version": 3,
    "prompt_version": "v1",
}
MARKER = build_marker(REQUEST)
ALIAS = alias_for(BRIEF_HASH)


def _page(marker: str, name: str = BRAND_DOC["name"]) -> str:
    return (
        f'<!doctype html><html><head><meta name="epyhia-build" content="{marker}">'
        f"</head><body><h1>{name}</h1></body></html>"
    )


def _api_response(request: httpx.Request, alias_status: int) -> httpx.Response:
    """The Vercel REST API, stubbed at the transport. No network, no token, no account."""
    if request.url.path == "/v13/deployments" and request.method == "POST":
        return httpx.Response(200, json={"id": "dpl_test", "url": "dpl-test.vercel.app"})
    if request.url.path.startswith("/v13/deployments/"):
        return httpx.Response(200, json={"readyState": "READY"})
    if request.url.path.endswith("/aliases"):
        return httpx.Response(alias_status, json={})
    return httpx.Response(404)


def _adapter(
    *, alias_status: int = 200, serves: str | None = None, calls: list | None = None
) -> VercelAdapter:
    """One adapter whose transport answers both the API and the deployed alias, so a test
    can drive execute() and verify() against the same stub."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            body = json.loads(request.content) if request.content else None
            calls.append((request.method, str(request.url), body))
        if request.url.host == "api.vercel.com":
            return _api_response(request, alias_status)
        return httpx.Response(200, text=serves or "")

    adapter = VercelAdapter(transport=httpx.MockTransport(handler))
    adapter.poll_interval_seconds = 0
    return adapter


class _Credentials:
    def require(self, provider: str) -> str:
        return "test-token"


def _ctx() -> GateContext:
    return GateContext(run_id=uuid.uuid4(), brand_doc=BRAND_DOC, credentials=_Credentials())


async def test_happy_path_deploys_inline_and_proves_the_derived_alias() -> None:
    calls: list = []
    adapter = _adapter(serves=_page(MARKER), calls=calls)

    result = await adapter.execute(REQUEST, _ctx())

    create = next(body for _, url, body in calls if url.endswith("/v13/deployments"))
    assert create["name"] == f"epyhia-{BRIEF_HASH[:12]}"
    assert create["target"] == "production"
    assert create["projectSettings"] == {
        "framework": None,
        "buildCommand": None,
        "outputDirectory": ".",
    }

    # The marker goes on at upload time; the bytes we were handed stay untouched (R3, FR-019).
    uploaded = base64.b64decode(create["files"][0]["data"]).decode("utf-8")
    assert f'content="{MARKER}"' in uploaded
    assert f'content="{MARKER}"' not in MARKUP

    alias_call = next(body for _, url, body in calls if url.endswith("/aliases"))
    assert alias_call["alias"] == ALIAS

    calls.clear()
    evidence = await adapter.verify(
        REQUEST, result | {"url": "https://a-different-url.vercel.app"}, _ctx()
    )

    # Probes the alias it derives, never the URL the API handed back (§4.5, R2).
    assert [url for _, url, _ in calls] == [f"https://{ALIAS}"]
    assert evidence == {
        "status": 200,
        "matched_name": BRAND_DOC["name"],
        "matched_build_marker": MARKER,
        "url": f"https://{ALIAS}",
    }


async def test_alias_conflict_is_treated_as_success() -> None:
    """409 means the alias is already assigned to this deployment — the behaviour a second
    deploy needs, not an error (R2)."""
    result = await _adapter(alias_status=409).execute(REQUEST, _ctx())

    assert result["readyState"] == "READY"
    assert result["deployment_id"] == "dpl_test"


async def test_verify_rejects_a_page_with_no_marker_at_all() -> None:
    body = f"<html><head></head><body>{BRAND_DOC['name']}</body></html>"

    with pytest.raises(VerificationFailed):
        await _adapter(serves=body).verify(REQUEST, {}, _ctx())


async def test_stale_alias_lands_failed_rather_than_succeeded(
    gate_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The alias answers 200 while still serving the previous build. A deploy that only
    checks for 200 passes this and is wrong (US1 scenario 6, FR-019, SC-002)."""
    monkeypatch.setattr(settings, "vercel_token", "test-token")
    run_id = await _seed_clean_run(gate_session)

    previous_build = build_marker(REQUEST | {"brand_doc_version": 2})
    registry.register(_adapter(serves=_page(previous_build)))

    with pytest.raises(ApprovalRequired):
        await gate.request(
            gate_session,
            run_id=run_id,
            requested_by="web_builder",
            action_type="deploy",
            action_request=REQUEST,
            idempotency_key=str(uuid.uuid4()),
            brand_doc=BRAND_DOC,
        )

    action_id = (
        await gate_session.execute(
            text("SELECT id FROM actions WHERE run_id = :run_id"), {"run_id": run_id}
        )
    ).scalar_one()
    result = await gate.approve(gate_session, action_id, "auth0|tester", brand_doc=BRAND_DOC)

    assert result["state"] == "failed"
    assert result["state"] != "succeeded"
    assert result["evidence"] is None
    assert "serves build" in result["error"]


async def _seed_clean_run(session: AsyncSession) -> uuid.UUID:
    """The `deploy` precondition reads a `clean` site artifact for the run, so one has to
    exist before the gate lets the action through at all (contracts/action-gate.md §5)."""
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
        {"id": run_id, "brief_id": brief_id, "alias": ALIAS},
    )
    await session.execute(
        text(
            "INSERT INTO artifacts (id, run_id, kind, path, content_type, bytes, sha256, "
            "grounding_status, revision) "
            "VALUES (:id, :run_id, 'site', 'index.html', 'text/html', :bytes, :sha, 'clean', 0)"
        ),
        {"id": uuid.uuid4(), "run_id": run_id, "bytes": b"<html></html>", "sha": "0" * 64},
    )
    await session.commit()
    return run_id


async def test_an_ampersand_in_the_name_verifies_against_the_escaped_body() -> None:
    """Regression test: the probe compared the stored name against raw HTML, where "&" is
    legitimately "&amp;" — so the first client with an ampersand in its name failed
    verification on a page that presented it correctly, three times over (run a9f3d800).
    The comparison happens in text space; the marker check stays on the raw markup."""
    name = "Rook & Lantern Supply"
    escaped_page = (
        f'<!doctype html><html><head><meta name="epyhia-build" content="{MARKER}">'
        f"</head><body><h1>Rook &amp; Lantern Supply</h1></body></html>"
    )
    adapter = _adapter(serves=escaped_page)
    ctx = GateContext(
        run_id=uuid.uuid4(), brand_doc={"name": name}, credentials=_Credentials()
    )

    evidence = await adapter.verify(REQUEST, {}, ctx)

    assert evidence["matched_name"] == name
    assert evidence["status"] == 200


async def test_a_name_genuinely_absent_still_fails_after_unescaping() -> None:
    """The unescape must not weaken the probe: a page without the name is still a refusal."""
    adapter = _adapter(serves=_page(MARKER, name="Some Other Business"))

    with pytest.raises(VerificationFailed, match="does not present the brand doc name"):
        await adapter.verify(REQUEST, {}, _ctx())
