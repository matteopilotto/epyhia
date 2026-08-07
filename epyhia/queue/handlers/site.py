import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.gate.adapters  # noqa: F401  — registers the deploy pair
from epyhia.agents.web_builder import build_site
from epyhia.artifacts.store import PostgresArtifactStore
from epyhia.gate import gate
from epyhia.gate.keys import deploy_key
from epyhia.ingest.extractors import extract_site_text
from epyhia.ingest.grounding import set_difference
from epyhia.ingest.normalise import find_amounts
from epyhia.models.artifacts import Artifact
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import register_handler

_store = PostgresArtifactStore()

AGENT = "web_builder"


class UpstreamNotClean(Exception):
    """The copy this page would be built from is not fit to be rendered. The task fails and
    the sweeper decides whether it is worth another attempt (R8)."""


def check_grounding(html: str, grounding_set: dict, locale: str) -> list[dict]:
    """Every numeral on the rendered page, set-differenced against what the brief actually
    said. Deterministic, and it runs before any model is asked an opinion about the page
    (FR-016, FR-022, Principle VI). The extractor's scope is R5's: text nodes outside
    `<script>`/`<style>` plus a few attributes — never a hex colour or a `rem` value."""
    extracted = [
        amount
        for text in extract_site_text(html)
        for amount in find_amounts(text, locale)
    ]
    return [
        {"value": str(v.value), "currency": v.currency}
        for v in set_difference(extracted, grounding_set)
    ]


async def handle_site(session: AsyncSession, task: Task) -> None:
    run = await session.get(Run, task.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id)
    brief = await session.get(Brief, run.brief_id)

    copy_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.kind == "copy")
            .order_by(Artifact.revision.desc())
        )
    ).scalars().first()

    # `copy → site` is an ordering edge, not a gate: without this the Reviewer's held claim
    # is rendered into a page and parked one operator click from deploy. The refusal sits
    # ahead of `build_site`, so a flagged copy costs no model call, produces no site
    # artifact, and requests no deploy.
    if copy_artifact is None:
        raise UpstreamNotClean("no copy artifact for this run")
    if copy_artifact.grounding_status != "clean":
        raise UpstreamNotClean(
            f"copy artifact is {copy_artifact.grounding_status}, not clean"
        )

    copy = json.loads(copy_artifact.bytes)

    html = await build_site(
        session,
        run_id=run.id,
        brand_doc=brand_doc.doc,
        copy=copy,
        task_id=task.id,
    )

    violations = check_grounding(html, run.grounding_set, brief.payload["locale"])
    await _store.write(
        session,
        run_id=run.id,
        kind="site",
        path="index.html",
        content_type="text/html",
        content=html.encode("utf-8"),
        grounding_status="clean" if not violations else "flagged",
        violations=violations or None,
    )

    # The gate re-reads that status as a precondition and refuses a flagged run's deploy
    # (contracts/action-gate.md §5). Requesting it here rather than from inside the Web
    # Builder is what makes that ordering unavoidable: there is no path on which a page
    # reaches the world before its numerals have been checked.
    await session.commit()
    await gate.request(
        session,
        run_id=run.id,
        requested_by=AGENT,
        action_type="deploy",
        action_request={
            "files": [{"file": "index.html", "data": html}],
            "brief_hash": brief.content_sha256,
            "brand_doc_version": brand_doc.version,
            "prompt_version": run.prompt_version,
        },
        idempotency_key=deploy_key(
            brief.content_sha256, brand_doc.version, run.prompt_version
        ),
        task_id=task.id,
        brand_doc=brand_doc.doc,
    )


register_handler("site", handle_site)
