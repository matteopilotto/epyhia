import json
import uuid
from pathlib import Path

import jsonschema
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.runs import Run

router = APIRouter(dependencies=[Depends(require_operator)])

# The parameterisation contract. Fixed structure, per-client contents — the schema must not
# change to accommodate one client (contracts/brand-doc.schema.json).
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "001-epyhia-agency"
    / "contracts"
    / "brand-doc.schema.json"
)
_VALIDATOR = jsonschema.Draft202012Validator(json.loads(_SCHEMA_PATH.read_text()))


def _serialize(brand_doc: BrandDoc) -> dict:
    return {
        "id": brand_doc.id,
        "brief_id": brand_doc.brief_id,
        "version": brand_doc.version,
        "doc": brand_doc.doc,
        "authored_by": brand_doc.authored_by,
        "created_at": brand_doc.created_at,
    }


def _leaves(value, prefix: str = "") -> dict[str, object]:
    """Flatten a doc to dotted paths, so a diff reads as a list of fields rather than as two
    walls of JSON. Lists are indexed, because a reordered `composition_plan` is a change."""
    if isinstance(value, dict):
        return {
            path: leaf
            for key, item in value.items()
            for path, leaf in _leaves(item, f"{prefix}.{key}" if prefix else key).items()
        }
    if isinstance(value, list):
        return {
            path: leaf
            for index, item in enumerate(value)
            for path, leaf in _leaves(item, f"{prefix}[{index}]").items()
        }
    return {prefix: value}


def diff_docs(before: dict, after: dict) -> list[dict]:
    """Field-level changes between two versions, `null` standing for absence on either side."""
    left, right = _leaves(before), _leaves(after)
    return [
        {"path": path, "from": left.get(path), "to": right.get(path)}
        for path in sorted(left.keys() | right.keys())
        if left.get(path) != right.get(path)
    ]


async def _load_run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "run not found"}
        )
    return run


@router.get("/runs/{run_id}/brand-doc")
async def get_run_brand_doc(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    """The version this run is parameterised by — not the brief's newest. A run reads the row
    it was pointed at, which is what makes an edit a second publication rather than a silent
    rewrite of the first."""
    run = await _load_run(session, run_id)
    brand_doc = (
        await session.get(BrandDoc, run.brand_doc_id) if run.brand_doc_id else None
    )
    if brand_doc is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "detail": "run has no brand doc yet"},
        )
    return _serialize(brand_doc)


@router.put("/runs/{run_id}/brand-doc")
async def put_run_brand_doc(
    run_id: uuid.UUID,
    payload: dict,
    claims: dict = Depends(require_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Insert `version + 1`; never update in place (FR-012, §5.3).

    Append-only is what keeps an edit distinguishable from a duplicate in the audit trail:
    the first version's deploy key stands, its publication stays live at its immutable URL,
    and the re-run against the new version computes a different key and therefore genuinely
    publishes a second time (§7.2, US4 scenario 3).
    """
    violations = list(_VALIDATOR.iter_errors(payload))
    if violations:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "detail": [
                    {"path": list(v.path), "message": v.message} for v in violations
                ],
            },
        )

    run = await _load_run(session, run_id)
    next_version = await session.scalar(
        select(func.coalesce(func.max(BrandDoc.version), 0) + 1).where(
            BrandDoc.brief_id == run.brief_id
        )
    )

    brand_doc = BrandDoc(
        id=uuid.uuid4(),
        brief_id=run.brief_id,
        version=next_version,
        doc=payload,
        authored_by=claims["sub"],
    )
    session.add(brand_doc)
    await session.flush()

    # The run is re-pointed, so the stages it re-runs read the edit. Without this the edit
    # would be recorded and then ignored, which is the failure §5.3's demo exists to catch.
    run.brand_doc_id = brand_doc.id
    await session.commit()
    return _serialize(brand_doc)


@router.get("/briefs/{brief_id}/brand-docs")
async def list_brand_docs(
    brief_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    """Every version, oldest first — the audit trail an edit is legible in."""
    result = await session.execute(
        select(BrandDoc).where(BrandDoc.brief_id == brief_id).order_by(BrandDoc.version)
    )
    return [_serialize(brand_doc) for brand_doc in result.scalars().all()]


@router.get("/briefs/{brief_id}/brand-docs/diff")
async def diff_brief_brand_docs(
    brief_id: uuid.UUID,
    from_version: int = Query(alias="from"),
    to_version: int = Query(alias="to"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """What changed between two versions of this brief's brand doc.

    Every value in the response is read from the rows themselves — there is no field this
    endpoint knows the meaning of, which is what keeps client data out of source (Principle I).
    """
    result = await session.execute(
        select(BrandDoc).where(
            BrandDoc.brief_id == brief_id,
            BrandDoc.version.in_([from_version, to_version]),
        )
    )
    by_version = {row.version: row for row in result.scalars().all()}
    missing = [v for v in (from_version, to_version) if v not in by_version]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "detail": f"no brand doc version {', '.join(str(v) for v in missing)}",
            },
        )

    return {
        "brief_id": brief_id,
        "from": from_version,
        "to": to_version,
        "changes": diff_docs(by_version[from_version].doc, by_version[to_version].doc),
    }
