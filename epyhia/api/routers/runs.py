import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.runs import Run

router = APIRouter(dependencies=[Depends(require_operator)])


async def _serialize(session: AsyncSession, run: Run) -> dict:
    brand_doc_version = None
    if run.brand_doc_id is not None:
        brand_doc = await session.get(BrandDoc, run.brand_doc_id)
        brand_doc_version = brand_doc.version if brand_doc else None
    return {
        "id": run.id,
        "brief_id": run.brief_id,
        "status": run.status,
        "brand_doc_version": brand_doc_version,
        "prompt_version": run.prompt_version,
        "spend_usd": run.spend_usd,
        "budget_usd": run.budget_usd,
        "alias": run.alias,
    }


@router.get("/runs")
async def list_runs(session: AsyncSession = Depends(get_session)) -> list[dict]:
    result = await session.execute(select(Run).order_by(Run.created_at.desc()))
    return [await _serialize(session, run) for run in result.scalars().all()]


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "run not found"}
        )
    return await _serialize(session, run)
