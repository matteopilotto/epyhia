import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.config import settings
from epyhia.gate.keys import alias_for
from epyhia.ingest.grounding import build_grounding_set
from epyhia.ingest.guardrail import screen_brief
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
    verdict = await screen_brief(payload)

    brief = Brief(
        id=uuid.uuid4(),
        payload=payload,
        content_sha256=brief_hash,
        guardrail_decision=verdict.decision,
        guardrail_reason=verdict.reason,
        guardrail_model=verdict.model,
    )
    session.add(brief)
    await session.commit()

    if verdict.decision == "reject":
        return JSONResponse(
            status_code=422,
            content={"error": "guardrail_rejected", "detail": verdict.reason},
        )

    alias = alias_for(brief_hash)
    run = Run(
        id=uuid.uuid4(),
        brief_id=brief.id,
        prompt_version=prompt_service.active_version("strategist"),
        grounding_set=build_grounding_set(payload, datetime.now(UTC).year),
        budget_usd=float(settings.run_budget_usd),
        status="running",
        alias=alias,
    )
    session.add(run)
    await session.flush()

    session.add(Task(id=uuid.uuid4(), run_id=run.id, kind="plan", state="pending"))
    await session.commit()

    return {
        "run_id": run.id,
        "brief_id": brief.id,
        "content_sha256": brief_hash,
        "alias": alias,
    }
