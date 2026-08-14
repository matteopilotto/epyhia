import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.gate.adapters  # noqa: F401  — registers the deploy pair
from epyhia.agents.site_critic import CritiqueFinding, critique
from epyhia.agents.web_builder import build_site, revise_site
from epyhia.artifacts.store import PostgresArtifactStore
from epyhia.config import settings
from epyhia.design.fonts import ResolvedPairing, embed_fonts, library
from epyhia.design.lint import DesignFinding, lint
from epyhia.design.screenshot import capture
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

logger = logging.getLogger(__name__)

_store = PostgresArtifactStore()

AGENT = "web_builder"

# The share of the original's text blocks a revision has to come back with to count as a
# revision at all. A lint count measures tells, not existence: a truncated generation leaves
# a document with no text in it, which grounds clean (nothing to flag), sizes small (the
# fonts are not the page) and ties on tells — every keep condition satisfied *because* there
# is nothing there. Deliberately generous, since a revision may legitimately merge or rewrite
# copy blocks; what it may not do is come back with almost none of them.
MIN_TEXT_RETENTION = 0.5


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


def design_report(
    findings: list[DesignFinding],
    *,
    screenshots: dict,
    critique_record: dict,
    revision: dict,
) -> dict:
    """What the built page carries and what looking at it again did, shaped by
    `contracts/design-report.schema.json`.

    Written on every path a build reaches — clean, flagged, skipped or revised: a report that
    only appears when something is wrong is one an operator has to interpret by its absence
    (FR-008), and the degraded paths are exactly the ones worth being able to see.
    """
    return {
        "lint": [finding.model_dump() for finding in findings],
        "critique": critique_record,
        "revision": revision,
        "screenshots": screenshots,
    }


def punch_list(
    findings: list[DesignFinding], critique_findings: list[CritiqueFinding]
) -> list[dict]:
    """The two checks' findings as one list, which is what gates the revision pass and what
    the builder is handed. `source` is kept on every entry: the lint counted the markup, the
    critic looked at the render, and a builder weighing a finding is entitled to know which."""
    return [
        {
            "source": "lint",
            "kind": finding.rule,
            "where": finding.where,
            "what": finding.detail,
        }
        for finding in findings
    ] + [
        {
            "source": "critic",
            "kind": finding.kind,
            "where": finding.where,
            "what": finding.what,
        }
        for finding in critique_findings
    ]


async def review_page(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    brand_doc: dict,
    page: str,
    findings: list[DesignFinding],
    task_id: uuid.UUID,
) -> tuple[dict, dict, list[CritiqueFinding]]:
    """Render the page and have the Site Critic look at it.

    Every failure on this path is a recorded skip rather than a raise: a missing browser, a
    render that never finished, a critic that could not produce its typed punch list. The
    visual review makes a page better; a run that fails because a review of it failed is
    strictly worse than one that ships the page it already checked (FR-015).

    A schema-valid empty punch list is `clean` and a failure is `skipped`. Neither triggers a
    revision, and the two are recorded distinctly so an operator can tell "the critic
    approved" from "the critic never usefully ran" (research R5).
    """
    shots = await capture(page)
    if not shots.captured:
        return (
            {"captured": False, "widths": []},
            {"status": "skipped", "findings": [], "skip_reason": shots.unavailable},
            [],
        )

    captured = {"captured": True, "widths": list(shots.widths)}
    try:
        review = await critique(
            session,
            run_id=run_id,
            brand_doc=brand_doc,
            findings=findings,
            screenshots=shots.images,
            task_id=task_id,
        )
    except Exception as exc:
        # `str(exc)` rather than `exc`: a log record holding the exception holds its traceback,
        # which holds this frame's locals — including ORM instances that then outlive the
        # stage in the session's identity map and go stale.
        logger.warning("site critic skipped: %s", str(exc))
        return (
            captured,
            {
                "status": "skipped",
                "findings": [],
                "skip_reason": f"the site critic returned no usable punch list: {exc}",
            },
            [],
        )

    return (
        captured,
        {
            "status": "clean" if review.clean else "findings",
            "findings": [finding.model_dump() for finding in review.findings],
        },
        review.findings,
    )


async def revise_page(
    session: AsyncSession,
    *,
    run: Run,
    brief: Brief,
    brand_doc: BrandDoc,
    copy: dict,
    pairing: ResolvedPairing,
    markup: str,
    findings: list[DesignFinding],
    critique_findings: list[CritiqueFinding],
    task_id: uuid.UUID,
) -> tuple[dict, str | None]:
    """Exactly one revision pass, and the decision about whether to keep what it produced.

    `markup` is the page as the builder wrote it, *before* the faces were injected — the
    same document the build pass produced. Handing the model the embedded page would spend
    its output ceiling reproducing ~114 KB of base64 woff2 before it reached any content,
    and would have it copy a font block the injector then adds a second time. The faces are
    put back here, exactly as the build path does it (FR-003).

    The revision earns its place or it is discarded: it is embedded, sized, grounded and
    linted exactly as the original was, and it replaces the original only if it is still a
    page, grounding is clean, and it counts no more tells than the page it was revising. A
    revision that fails any of those is a record in the design report, never an artifact
    (FR-014, SC-003).

    There is no second pass. The failure of this call is a recorded skip like the critic's.
    """
    before = len(findings)
    try:
        revised = embed_fonts(
            await revise_site(
                session,
                run_id=run.id,
                brand_doc=brand_doc.doc,
                brand_doc_version=brand_doc.version,
                copy=copy,
                checkout=checkout_context(run),
                pairing=pairing,
                page=markup,
                findings=punch_list(findings, critique_findings),
                task_id=task_id,
            ),
            pairing,
        )
    except Exception as exc:
        # Over budget or malformed lands here too: the original page is already stored,
        # already checked and already deployable, so a runaway revision costs the pass and
        # nothing else.
        logger.warning("site revision skipped: %s", str(exc))
        return {
            "outcome": "skipped",
            "findings_before": before,
            "skip_reason": f"the revision pass did not produce a usable page: {exc}",
        }, None

    violations = check_grounding(revised, run.grounding_set, brief.payload["locale"])
    after = len(lint(revised, brand_doc=brand_doc.doc, pairing=pairing))
    record = {"outcome": "kept", "findings_before": before, "findings_after": after}

    # First, so the report names the real reason: a document with nothing in it satisfies
    # every condition below rather than failing one, and "kept" would be the honest-looking
    # record of a blank page one operator click from deploy. Counted with the extractor the
    # grounding check already runs, against the document this pass was revising.
    if len(extract_site_text(revised)) < MIN_TEXT_RETENTION * len(
        extract_site_text(markup)
    ):
        record["outcome"] = "discarded_empty"
        return record, None
    if violations:
        # A revision may not smuggle in a numeral the brief never stated, and the answer is
        # not to flag the run: the original page passed this same check and is still here.
        record["outcome"] = "discarded_grounding"
        return record, None
    if after > before:
        record["outcome"] = "discarded_worse"
        return record, None
    return record, revised


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

    # Newest generation, not highest revision: `revision` counts review rounds *within* one
    # `produce()` call, so after an operator re-runs the copy stage the fresh clean artifact
    # (revision 0, passed first draft) would lose to the stale flagged one (revision 2) and
    # this stage would refuse forever on copy the run no longer stands behind.
    copy_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.kind == "copy")
            .order_by(Artifact.created_at.desc(), Artifact.revision.desc())
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
    # the only mechanical bar between a page and the world (FR-010).
    findings = lint(page, brand_doc=brand_doc.doc, pairing=pairing)

    if violations:
        # A flagged page is not on its way anywhere — the gate refuses its deploy — so the
        # loop would spend two model calls on a page nobody will see. Skipping it also keeps
        # US2's posture exactly as it was: a revision that came back clean would otherwise
        # quietly turn a refused run into a deployed one.
        skip = "the page is flagged for ungrounded numerals and will not be deployed"
        screenshots = {"captured": False, "widths": []}
        critique_record = {"status": "skipped", "findings": [], "skip_reason": skip}
        revision = {
            "outcome": "skipped",
            "findings_before": len(findings),
            "skip_reason": skip,
        }
    else:
        # The builder sees its own work before it ships. Both steps degrade to a recorded
        # skip rather than a failure, so the stage always arrives at the deploy request.
        screenshots, critique_record, critique_findings = await review_page(
            session,
            run_id=run.id,
            brand_doc=brand_doc.doc,
            page=page,
            findings=findings,
            task_id=task.id,
        )

        revision = {"outcome": "not_needed", "findings_before": len(findings)}
        if findings or critique_findings:
            revision, revised = await revise_page(
                session,
                run=run,
                brief=brief,
                brand_doc=brand_doc,
                copy=copy,
                pairing=pairing,
                # The builder's own markup, not the stored page: `html` is the pre-embedding
                # document and the fonts go back on inside (FR-003).
                markup=html,
                findings=findings,
                critique_findings=critique_findings,
                task_id=task.id,
            )
            if revised is not None:
                # Revision 1, and only when it is kept: the existing `ORDER BY revision DESC`
                # readers — export, console, the deploy request below — pick up the better
                # page with nothing to change. A discarded revision leaves no artifact; its
                # record is the report.
                page = revised
                site = await _store.write(
                    session,
                    run_id=run.id,
                    kind="site",
                    path="index.html",
                    content_type="text/html",
                    content=page.encode("utf-8"),
                    grounding_status="clean",
                    revision=site.revision + 1,
                )

    # Internal telemetry — never deployed, sent or published — which is why its grounding
    # status is asserted by construction rather than scanned (research R7). Its revision
    # matches the site build it describes.
    report = design_report(
        findings,
        screenshots=screenshots,
        critique_record=critique_record,
        revision=revision,
    )
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
