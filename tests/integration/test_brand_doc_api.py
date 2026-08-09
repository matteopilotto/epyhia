import copy
import json
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.app import create_app
from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
OPERATOR = "auth0|operator"


def brief_payload() -> dict:
    return json.loads((_FIXTURES / "briefs" / "one.json").read_text())


def client_for(session: AsyncSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_operator] = lambda: {"sub": OPERATOR}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    )


async def seed(session: AsyncSession) -> tuple[Run, BrandDoc]:
    """A brief, a run, and the brand doc the Strategist would have written for it.

    The doc is derived from the fixture brief rather than typed out here — the values this
    test asserts on come from the run's own rows and appear nowhere in source (Principle I).
    """
    payload = brief_payload()
    brief = Brief(
        id=uuid.uuid4(),
        payload=payload,
        content_sha256=uuid.uuid4().hex,
        guardrail_decision="pass",
        guardrail_model="test-model",
    )
    session.add(brief)
    await session.flush()

    doc = {
        "name": payload["business_name"],
        "descriptor": payload["one_liner"],
        "positioning": payload["one_liner"],
        "palette": {
            "bg": "#101014",
            "fg": "#f4f4f5",
            "accent": "#c2410c",
            "muted": "#71717a",
        },
        "type": {"display": "Display Face", "body": "Body Face"},
        "motion_language": "mechanical, deliberate",
        "composition_archetype": "editorial_stack",
        "video_archetype": "technical_spec_sheet",
        "voice": {"adjectives": ["plain"], "do": ["say it once"], "dont": ["no shouting"]},
        "composition_plan": [
            {"section": "opening", "layout": "hero_stacked", "intent": "state what this is"}
        ],
        "offerings": [
            {
                "name": product["name"],
                "description": product["description"],
                "price_minor": product["price_minor"],
                "currency_display": product["currency_display"],
                "billing": product["billing"],
                "features": product["features"],
                "not_covered": product["not_covered"],
            }
            for product in payload["products"]
        ],
    }
    brand_doc = BrandDoc(
        id=uuid.uuid4(), brief_id=brief.id, version=1, doc=doc, authored_by="strategist"
    )
    session.add(brand_doc)

    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        brand_doc_id=brand_doc.id,
        prompt_version="v1",
        grounding_set={},
        resolved_catalogue=[],
        budget_usd=25,
        status="running",
        alias=f"epyhia-{uuid.uuid4().hex[:12]}.vercel.app",
    )
    session.add(run)
    await session.commit()
    return run, brand_doc


async def test_get_returns_the_version_the_run_is_pointed_at(
    integration_session: AsyncSession,
) -> None:
    run, brand_doc = await seed(integration_session)
    async with client_for(integration_session) as client:
        response = await client.get(f"/runs/{run.id}/brand-doc")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["doc"] == brand_doc.doc


async def test_put_inserts_version_plus_one_and_never_updates_in_place(
    integration_session: AsyncSession,
) -> None:
    """Append-only (FR-012). The first version has to survive the edit, or an edit and a
    duplicate become indistinguishable in the audit trail."""
    run, first = await seed(integration_session)
    edited = copy.deepcopy(first.doc)
    edited["palette"]["accent"] = "#0ea5e9"

    async with client_for(integration_session) as client:
        response = await client.put(f"/runs/{run.id}/brand-doc", json=edited)

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["authored_by"] == OPERATOR

    versions = (
        await integration_session.execute(
            select(BrandDoc).where(BrandDoc.brief_id == run.brief_id).order_by(BrandDoc.version)
        )
    ).scalars().all()
    assert [row.version for row in versions] == [1, 2]
    assert versions[0].doc == first.doc

    # Re-pointed, so the stages this run re-runs read the edit rather than recording it and
    # then ignoring it.
    await integration_session.refresh(run)
    assert run.brand_doc_id == versions[1].id


async def test_put_refuses_a_doc_the_contract_rejects(
    integration_session: AsyncSession,
) -> None:
    run, first = await seed(integration_session)
    without_name = {k: v for k, v in first.doc.items() if k != "name"}

    async with client_for(integration_session) as client:
        response = await client.put(f"/runs/{run.id}/brand-doc", json=without_name)

    assert response.status_code == 400
    assert (
        await integration_session.scalar(
            select(BrandDoc.version)
            .where(BrandDoc.brief_id == run.brief_id)
            .order_by(BrandDoc.version.desc())
        )
        == 1
    )


async def test_diff_names_the_changed_field_and_both_of_its_values(
    integration_session: AsyncSession,
) -> None:
    run, first = await seed(integration_session)
    edited = copy.deepcopy(first.doc)
    edited["palette"]["accent"] = "#0ea5e9"

    async with client_for(integration_session) as client:
        await client.put(f"/runs/{run.id}/brand-doc", json=edited)
        response = await client.get(
            f"/briefs/{run.brief_id}/brand-docs/diff", params={"from": 1, "to": 2}
        )

    assert response.status_code == 200
    assert response.json()["changes"] == [
        {
            "path": "palette.accent",
            "from": first.doc["palette"]["accent"],
            "to": edited["palette"]["accent"],
        }
    ]


async def test_diff_against_a_version_that_does_not_exist_is_a_404(
    integration_session: AsyncSession,
) -> None:
    run, _ = await seed(integration_session)
    async with client_for(integration_session) as client:
        response = await client.get(
            f"/briefs/{run.brief_id}/brand-docs/diff", params={"from": 1, "to": 2}
        )
    assert response.status_code == 404
