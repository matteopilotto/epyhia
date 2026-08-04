import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents import marketer, reviewer
from epyhia.artifacts.store import PostgresArtifactStore
from epyhia.ingest.extractors import extract_structured_strings
from epyhia.ingest.grounding import set_difference
from epyhia.ingest.normalise import GroundingEntry, find_amounts
from epyhia.models.artifacts import Artifact

_store = PostgresArtifactStore()

# One initial draft and at most two revisions (FR-024). The bound exists because the
# Reviewer can be wrong about voice and an unbounded loop against a fallible judge is an
# unbounded bill; the deterministic numeric check, which cannot be wrong, is what makes
# stopping safe (§12 risks).
MAX_REVISIONS = 2

# Sent to the Marketer as the `why` of a numeral violation. Not a prompt — the instructions
# live in `prompts/marketer/v1.jinja`; this is the one sentence that explains a machine
# finding, and it carries no client data by construction.
UNGROUNDED_NUMERAL_WHY = "this amount is not among the numbers the business stated"


def numeral_violations(payload: dict, grounding_set: dict, locale: str) -> list[dict]:
    """The deterministic half of the check, and it runs before the Reviewer is called at
    all (FR-022, Principle VI). Exact, free, and not a matter of opinion — so asking a
    model about a draft that already fails it would be spending money to be told something
    already known.

    Scope here is the structured-artifact rule from research.md R5: every string value in
    the draft. `video_props` reads its leaves under `content` instead, wired in T083.
    """
    extracted: list[GroundingEntry] = [
        amount
        for text in extract_structured_strings(payload)
        for amount in find_amounts(text, locale)
    ]
    return [
        {
            "kind": "ungrounded_numeral",
            "quote": str(entry.value) if entry.currency is None
            else f"{entry.value} {entry.currency}",
            "why": UNGROUNDED_NUMERAL_WHY,
        }
        for entry in set_difference(extracted, grounding_set)
    ]


async def produce(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    deliverable: str,
    brand_doc: dict,
    brief: dict,
    grounding_set: dict,
    task_id: uuid.UUID | None = None,
) -> Artifact:
    """Draft, check, revise — then store, clean or flagged, either way.

    A draft that still carries violations after its revisions is written
    `grounding_status = 'flagged'` with the violations that survived, and it is written
    rather than dropped: a flagged artifact is listed, readable and surfaced in the console,
    because the failure mode this guards against is work disappearing quietly (FR-024).
    """
    locale = brief["locale"]
    previous: dict | None = None
    violations: list[dict] = []
    payload: dict = {}

    for revision in range(MAX_REVISIONS + 1):
        output = await marketer.draft(
            session,
            run_id=run_id,
            brand_doc=brand_doc,
            deliverable=deliverable,
            previous=previous,
            violations=violations or None,
            task_id=task_id,
        )
        payload = output.model_dump(exclude_none=True)

        violations = numeral_violations(payload, grounding_set, locale)
        if not violations:
            # Only now is a model asked an opinion, and only about voice and claims.
            review = await reviewer.review(
                session,
                run_id=run_id,
                draft=payload,
                brand_doc=brand_doc,
                brief=brief,
                task_id=task_id,
            )
            violations = [v.model_dump() for v in review.violations]

        if not violations:
            return await _write(session, run_id, deliverable, payload, [], revision)

        previous = payload

    return await _write(session, run_id, deliverable, payload, violations, MAX_REVISIONS)


async def _write(
    session: AsyncSession,
    run_id: uuid.UUID,
    deliverable: str,
    payload: dict,
    violations: list[dict],
    revision: int,
) -> Artifact:
    return await _store.write(
        session,
        run_id=run_id,
        kind=deliverable,
        path=f"{deliverable}.json",
        content_type="application/json",
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        grounding_status="clean" if not violations else "flagged",
        violations=violations or None,
        revision=revision,
    )
