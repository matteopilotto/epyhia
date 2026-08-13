import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.gate.adapters  # noqa: F401  — registers the deploy pair
from epyhia.agents.web_builder import build_site
from epyhia.artifacts.store import PostgresArtifactStore
from epyhia.config import settings
from epyhia.design.fonts import embed_fonts, library
from epyhia.design.lint import DesignFinding, lint
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


def design_report(findings: list[DesignFinding]) -> dict:
    """What the built page carries, shaped by `contracts/design-report.schema.json`.

    Written on every path a build reaches, a clean page included: a report that only appears
    when something is wrong is one an operator has to interpret by its absence (FR-008).

    The critique and revision fields are the loop US3 builds. They are recorded here as the
    skip and the not-needed they honestly are, rather than left out of a document whose shape
    would then change under the console the moment the loop lands.
    """
    return {
        "lint": [finding.model_dump() for finding in findings],
        "critique": {
            "status": "skipped",
            "findings": [],
            "skip_reason": "the review loop is not built at this prompt version",
        },
        "revision": {"outcome": "not_needed", "findings_before": len(findings)},
        "screenshots": {"captured": False, "widths": []},
    }


def checkout_context(run: Run) -> dict:
    """What the buy button needs, and nothing more.

    The slug comes from the run's resolved catalogue — derived from the brief at ingest — so
    the button is built against the same brief field Ops prices against, rather than against
    Ops' output. Neither task waits on the other, and no Stripe identifier is in reach of
    this markup at all (research.md R11, FR-030).
    """
    return {
        "endpoint": f"{(settings.public_api_url or '').rstrip('/')}/checkout",
        "run_id": str(run.id),
        "products": [
            {"name": row["name"], "slug": row["slug"]} for row in run.resolved_catalogue
        ],
    }


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

    # Before the model call, deliberately: an id nobody curated — including a free-text face
    # name from a brand doc written before ids existed — fails the stage here rather than
    # producing a page set in whatever the visitor's device happened to have (FR-005).
    pairing = library.resolve_pairing(
        brand_doc.doc["type"]["display"], brand_doc.doc["type"]["body"]
    )

    html = await build_site(
        session,
        run_id=run.id,
        brand_doc=brand_doc.doc,
        brand_doc_version=brand_doc.version,
        copy=copy,
        checkout=checkout_context(run),
        pairing=pairing,
        task_id=task.id,
    )

    # Embedding runs before the grounding check and before the store, so the artifact of
    # record is the exact bytes that were checked and are deployed — not a page the fonts
    # were added to somewhere further downstream. Over the size budget, the stage fails
    # visibly and nothing is stored (FR-006).
    page = embed_fonts(html, pairing)

    violations = check_grounding(page, run.grounding_set, brief.payload["locale"])
    site = await _store.write(
        session,
        run_id=run.id,
        kind="site",
        path="index.html",
        content_type="text/html",
        content=page.encode("utf-8"),
        grounding_status="clean" if not violations else "flagged",
        violations=violations or None,
    )

    # The stored bytes are what gets linted, so the report describes the page of record. It
    # never refuses anything: the tells are counted and made visible, and grounding remains
    # the only mechanical bar between a page and the world (FR-010). The report itself is
    # internal telemetry — never deployed, sent or published — which is why its grounding
    # status is asserted by construction rather than scanned (research R7).
    report = design_report(lint(page, brand_doc=brand_doc.doc, pairing=pairing))
    await _store.write(
        session,
        run_id=run.id,
        kind="design_report",
        path="design-report.json",
        content_type="application/json",
        content=json.dumps(report, indent=2).encode("utf-8"),
        grounding_status="clean",
        revision=site.revision,
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
            "files": [{"file": "index.html", "data": page}],
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
