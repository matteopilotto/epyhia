import hashlib
import io
import json
import uuid
import zipfile

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.app import create_app
from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.models.artifacts import Artifact
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from tests.integration.test_brand_doc_api import brief_payload, client_for

pytestmark = pytest.mark.asyncio

# Deliberately not valid UTF-8. The endpoint's contract is bytes out, unmodified — a stand-in
# for the rendered video, and the case a decode-and-re-encode round trip would corrupt.
BINARY = bytes(range(256)) * 8


def _artifact(run_id: uuid.UUID, kind: str, path: str, content_type: str, body: bytes) -> Artifact:
    return Artifact(
        id=uuid.uuid4(),
        run_id=run_id,
        kind=kind,
        path=path,
        content_type=content_type,
        bytes=body,
        sha256=hashlib.sha256(body).hexdigest(),
        grounding_status="clean",
        violations=None,
        revision=0,
    )


async def seed_run(session: AsyncSession) -> Run:
    """A brief and a run with nothing produced against it yet."""
    brief = Brief(
        id=uuid.uuid4(),
        payload=brief_payload(),
        content_sha256=uuid.uuid4().hex,
        guardrail_decision="pass",
        guardrail_model="test-model",
    )
    session.add(brief)
    await session.flush()

    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        prompt_version="v1",
        grounding_set={},
        resolved_catalogue=[],
        budget_usd=25,
        status="running",
        alias=f"epyhia-{uuid.uuid4().hex[:12]}.vercel.app",
    )
    session.add(run)
    await session.flush()
    return run


async def seed(session: AsyncSession) -> tuple[Run, Artifact, Artifact]:
    """A run with one text deliverable and one binary one.

    The text artifact's words come from the fixture brief rather than from this file, so
    nothing asserted here is client data typed into source (Principle I).
    """
    payload = brief_payload()
    run = await seed_run(session)

    text = _artifact(
        run.id,
        "copy",
        "copy.json",
        "application/json",
        json.dumps(
            {
                "sections": [
                    {
                        "section": "hero",
                        "headline": payload["one_liner"],
                        "body": payload["one_liner"],
                    }
                ]
            }
        ).encode("utf-8"),
    )
    video = _artifact(run.id, "video", "launch.mp4", "video/mp4", BINARY)
    session.add_all([text, video])
    await session.commit()
    return run, text, video


async def test_content_returns_the_stored_bytes_of_a_text_artifact(
    integration_session: AsyncSession,
) -> None:
    _, text, _ = await seed(integration_session)
    async with client_for(integration_session) as client:
        response = await client.get(f"/artifacts/{text.id}/content")

    assert response.status_code == 200
    # Byte-identity with the row is the contract the download hash check turns on (FR-006).
    assert hashlib.sha256(response.content).hexdigest() == text.sha256
    assert response.content == text.bytes
    assert response.headers["content-type"] == text.content_type
    assert response.headers["content-disposition"] == f'attachment; filename="{text.path}"'


async def test_content_returns_binary_bytes_undecoded(
    integration_session: AsyncSession,
) -> None:
    """The video path. Bytes that are not valid UTF-8 must cross the wire untouched — a
    replace-on-decode anywhere in the path yields a file that plays as garbage."""
    _, _, video = await seed(integration_session)
    async with client_for(integration_session) as client:
        response = await client.get(f"/artifacts/{video.id}/content")

    assert response.status_code == 200
    assert response.content == BINARY
    assert hashlib.sha256(response.content).hexdigest() == video.sha256
    assert response.headers["content-type"] == video.content_type
    assert response.headers["content-disposition"] == f'attachment; filename="{video.path}"'


async def test_content_for_an_unknown_artifact_is_a_404_in_the_standard_shape(
    integration_session: AsyncSession,
) -> None:
    await seed(integration_session)
    async with client_for(integration_session) as client:
        response = await client.get(f"/artifacts/{uuid.uuid4()}/content")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "detail": "artifact not found"}


async def test_content_without_a_bearer_token_is_a_401(
    integration_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Media retrieval carries the same auth as everything else — there is no second path in
    (FR-007, FR-057). This is the one test that leaves `require_operator` in place."""
    monkeypatch.setattr(settings, "auth0_domain", "epyhia.test.auth0.com")
    monkeypatch.setattr(settings, "auth0_audience", "https://api.epyhia.test")
    _, text, _ = await seed(integration_session)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: integration_session
    assert require_operator not in app.dependency_overrides
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test/api"
    ) as client:
        response = await client.get(f"/artifacts/{text.id}/content")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


async def test_pack_is_a_zip_named_from_the_run_alone(integration_session: AsyncSession) -> None:
    """The filename derives from the run id: a client name in it would be client data
    written by code (Principle I)."""
    run, _, _ = await seed(integration_session)
    async with client_for(integration_session) as client:
        response = await client.get(f"/runs/{run.id}/pack")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == f'attachment; filename="pack-{run.id}.zip"'
    assert zipfile.ZipFile(io.BytesIO(response.content)).testzip() is None


async def test_pack_manifest_describes_every_file_it_ships(
    integration_session: AsyncSession,
) -> None:
    """End to end, the SC-004 check an operator runs with `shasum`: hash what came out of
    the archive, compare with the manifest, and compare the record hashes with the rows."""
    run, text, video = await seed(integration_session)
    async with client_for(integration_session) as client:
        response = await client.get(f"/runs/{run.id}/pack")

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(zf.read("manifest.json"))

    assert manifest["run_id"] == str(run.id)
    assert {entry["archive_path"] for entry in manifest["files"]} == set(zf.namelist()) - {
        "manifest.json"
    }
    for entry in manifest["files"]:
        assert hashlib.sha256(zf.read(entry["archive_path"])).hexdigest() == entry["sha256"]

    records = {entry["kind"]: entry for entry in manifest["files"] if entry["role"] == "record"}
    assert records["copy"]["sha256"] == text.sha256
    assert records["video"]["sha256"] == video.sha256
    # The binary crosses two hops now — endpoint and archive — and is still the stored bytes.
    assert zf.read("deliverables/launch.mp4") == BINARY


async def test_pack_segregates_a_flagged_artifact_with_its_violations(
    integration_session: AsyncSession,
) -> None:
    run, _, _ = await seed(integration_session)
    payload = brief_payload()
    violations = [{"kind": "ungrounded_numeral", "quote": payload["one_liner"], "why": "not held"}]
    flagged = _artifact(
        run.id, "posts", "posts.json", "application/json", b'{"posts": "unparseable shape"}'
    )
    flagged.grounding_status = "flagged"
    flagged.violations = violations
    integration_session.add(flagged)
    await integration_session.commit()

    async with client_for(integration_session) as client:
        response = await client.get(f"/runs/{run.id}/pack")

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    names = zf.namelist()

    assert "flagged/posts.json" in names
    assert "deliverables/posts.json" not in names
    assert json.loads(zf.read("flagged/posts.violations.json")) == violations
    # Content that does not parse as its kind's shape ships as the record alone (FR-011).
    assert "flagged/posts.md" not in names


async def test_pack_for_a_run_with_no_artifacts_is_a_valid_empty_archive(
    integration_session: AsyncSession,
) -> None:
    """An accurate empty manifest, not an error — the in-progress run's answer (FR-008)."""
    run = await seed_run(integration_session)
    await integration_session.commit()

    async with client_for(integration_session) as client:
        response = await client.get(f"/runs/{run.id}/pack")

    assert response.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    assert zf.namelist() == ["manifest.json"]
    assert json.loads(zf.read("manifest.json"))["files"] == []


async def test_pack_for_an_unknown_run_is_a_404_in_the_standard_shape(
    integration_session: AsyncSession,
) -> None:
    """Distinct from the empty archive above: a run that produced nothing and a run that
    does not exist are different answers."""
    await seed(integration_session)
    async with client_for(integration_session) as client:
        response = await client.get(f"/runs/{uuid.uuid4()}/pack")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "detail": "run not found"}


async def test_pack_without_a_bearer_token_is_a_401(
    integration_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth0_domain", "epyhia.test.auth0.com")
    monkeypatch.setattr(settings, "auth0_audience", "https://api.epyhia.test")
    run, _, _ = await seed(integration_session)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: integration_session
    assert require_operator not in app.dependency_overrides
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test/api"
    ) as client:
        response = await client.get(f"/runs/{run.id}/pack")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
