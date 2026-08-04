import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.artifacts.store import PostgresArtifactStore
from epyhia.ingest.extractors import extract_structured_strings
from epyhia.ingest.grounding import set_difference
from epyhia.ingest.normalise import find_amounts
from epyhia.models.artifacts import Artifact

# Interim, and deliberately not an agent (DESIGN.md §12 step 6). US1 needs the `copy` →
# `site` seam to exist and to carry a real artifact; US2 replaces what fills it with the
# Marketer's reviewed copy, and the Web Builder does not change when it does (FR-021, T077).
#
# The shape is the contract that survives the swap:
#
#     {"sections": [{"section": ..., "headline": ..., "body": ...}, ...]}

_store = PostgresArtifactStore()


def build_copy(brand_doc: dict) -> dict:
    """One copy section per planned section, in plan order. The composition plan carries
    layout intent only — no price, no claim, no number — so neither does this."""
    return {
        "sections": [
            {
                "section": entry["section"],
                "headline": entry["section"],
                "body": entry["intent"],
            }
            for entry in brand_doc["composition_plan"]
        ]
    }


async def write_copy_stub(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    brand_doc: dict,
    grounding_set: dict,
    locale: str,
) -> Artifact:
    """Write the `copy` artifact, grounded exactly as the Marketer's will be — the check is
    an artifact-boundary property, not an agent's, so it holds for a stub too (Principle VI).
    """
    copy = build_copy(brand_doc)

    extracted = [
        amount
        for text in extract_structured_strings(copy)
        for amount in find_amounts(text, locale)
    ]
    violations = set_difference(extracted, grounding_set)

    return await _store.write(
        session,
        run_id=run_id,
        kind="copy",
        path="copy.json",
        content_type="application/json",
        content=json.dumps(copy, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        grounding_status="clean" if not violations else "flagged",
        violations=[{"value": str(v.value), "currency": v.currency} for v in violations]
        or None,
    )
