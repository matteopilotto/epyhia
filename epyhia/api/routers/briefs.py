import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.cost import budget
from epyhia.cost.ledger import record_call
from epyhia.gate.keys import alias_for
from epyhia.ingest import guardrail
from epyhia.ingest.catalogue import resolve_catalogue
from epyhia.ingest.grounding import build_grounding_set
from epyhia.ingest.hashing import content_sha256
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.prompts_service import prompt_service

router = APIRouter(dependencies=[Depends(require_operator)])

# The input contract lives with the spec (contracts/brief.schema.json) — this schema is
# fixed, its contents vary entirely by client (FR-001).
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "001-epyhia-agency"
    / "contracts"
    / "brief.schema.json"
)
_VALIDATOR = jsonschema.Draft202012Validator(json.loads(_SCHEMA_PATH.read_text()))


@router.post("/briefs", status_code=201, response_model=None)
async def submit_brief(
    payload: dict, session: AsyncSession = Depends(get_session)
) -> dict | JSONResponse:
    violations = list(_VALIDATOR.iter_errors(payload))
    if violations:
        return JSONResponse(
            status_code=400,
            content={
                "error": "validation_error",
                "detail": [
                    {"path": list(v.path), "message": v.message} for v in violations
                ],
            },
        )

    brief_hash = content_sha256(payload)

    # "Same run" means same brief hash and nothing else (FR-002). An identical resubmission
    # resolves to what already exists — it does not insert, does not open a second run, and
    # does not spend another guardrail call on a decision already on the row.
    existing = await session.scalar(
        select(Brief).where(Brief.content_sha256 == brief_hash)
    )
    if existing is not None:
        if existing.guardrail_decision == "reject":
            return JSONResponse(
                status_code=422,
                content={"error": "guardrail_rejected", "detail": existing.guardrail_reason},
            )
        run = await session.scalar(
            select(Run).where(Run.brief_id == existing.id).order_by(Run.created_at)
        )
        return JSONResponse(
            status_code=200,
            content={
                "run_id": str(run.id),
                "brief_id": str(existing.id),
                "content_sha256": brief_hash,
                "alias": run.alias,
                "deduplicated": True,
            },
        )

    # Below the dedup branch on purpose. The ceiling refuses to *open* runs, and an identical
    # resubmission opens none — it resolves to the run that already exists, so refusing it
    # would withhold a record of work already paid for while stopping nothing.
    await budget.assert_within_daily_ceiling(session)

    # Read before the guardrail's model call, not at run construction after it: an absent
    # `RUN_BUDGET_USD` is a refusal to open a run, and refusing after spending on a screening
    # call is spending against a budget that does not exist.
    run_budget = budget.configured_run_budget()

    verdict = await guardrail.screen_brief(payload)

    brief = Brief(
        id=uuid.uuid4(),
        payload=payload,
        content_sha256=brief_hash,
        guardrail_decision=verdict.decision,
        guardrail_reason=verdict.reason,
        guardrail_model=verdict.model,
    )
    session.add(brief)

    rejected = verdict.decision == "reject"

    # A rejected brief still opens a run — not to do work, but so the screening call has a run
    # to be recorded against and a budget to have spent from. Rejecting a brief is the one way
    # to make the system spend money; it must not also be the one way to spend it invisibly
    # (FR-034, FR-054, SC-007).
    alias = alias_for(brief_hash)
    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        prompt_version=prompt_service.active_version("strategist"),
        grounding_set=build_grounding_set(payload, datetime.now(UTC).year),
        # Derived here, at the same seam and for the same reason as the grounding set: the
        # slug the site's button carries and the one Ops prices against are one value,
        # computed from the brief before anything expensive runs (research.md R11).
        resolved_catalogue=resolve_catalogue(payload["products"]),
        budget_usd=run_budget,
        status="failed" if rejected else "running",
        alias=alias,
    )
    session.add(run)
    await session.flush()

    await record_call(
        session,
        run_id=run.id,
        task_id=None,
        agent=guardrail.AGENT,
        model_id=verdict.model,
        prompt_version=guardrail.PROMPT_VERSION,
        input_tokens=verdict.input_tokens,
        output_tokens=verdict.output_tokens,
        cache_write_tokens=verdict.cache_write_tokens,
        cache_read_tokens=verdict.cache_read_tokens,
        latency_ms=verdict.latency_ms,
        # No memo stands in front of the screen — every submitted brief is screened by the
        # model, so this row is never served from `agent_cache`.
        cache_hit=False,
    )

    if rejected:
        await session.commit()
        return JSONResponse(
            status_code=422,
            content={"error": "guardrail_rejected", "detail": verdict.reason},
        )

    session.add(Task(id=uuid.uuid4(), run_id=run.id, kind="plan", state="pending"))
    await session.commit()

    return {
        "run_id": run.id,
        "brief_id": brief.id,
        "content_sha256": brief_hash,
        "alias": alias,
    }
