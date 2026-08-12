import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.api.sse import SSEEvent, sse_response
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run

router = APIRouter(dependencies=[Depends(require_operator)])

POLL_SECONDS = 1.0

# The timeline is the four tables read in their own ordering column — `tasks` and `actions`
# carry `updated_at` because a state transition is itself an event, while an artifact and an
# agent call are written once (data-model.md). Every value is cast to something JSON can
# hold, so the stream never depends on a driver's type coercion.
_SOURCES: tuple[tuple[str, str], ...] = (
    (
        "task",
        "SELECT updated_at AS at, id::text AS id, kind, state FROM tasks "
        "WHERE run_id = :run_id AND updated_at > :since ORDER BY updated_at",
    ),
    (
        "action",
        "SELECT updated_at AS at, id::text AS id, action_type, state, idempotency_key, "
        "projected_cost_usd::float AS projected_cost_usd FROM actions "
        "WHERE run_id = :run_id AND updated_at > :since ORDER BY updated_at",
    ),
    (
        "artifact",
        "SELECT created_at AS at, id::text AS id, kind, path, grounding_status, revision "
        "FROM artifacts WHERE run_id = :run_id AND created_at > :since ORDER BY created_at",
    ),
    (
        "agent_call",
        "SELECT created_at AS at, id::text AS id, agent, model_id, tier, "
        "cost_usd::float AS cost_usd, latency_ms FROM agent_calls "
        "WHERE run_id = :run_id AND created_at > :since ORDER BY created_at",
    ),
)


async def _serialize(session: AsyncSession, run: Run) -> dict:
    brand_doc_version = None
    if run.brand_doc_id is not None:
        brand_doc = await session.get(BrandDoc, run.brand_doc_id)
        brand_doc_version = brand_doc.version if brand_doc else None
    brief = await session.get(Brief, run.brief_id)
    return {
        "id": run.id,
        "brief_id": run.brief_id,
        # Run identity is brief identity (§7.1), so the hash belongs on the row. It is how
        # the eval finds a run: it hashes the brief it was handed with ingest's own
        # canonicalisation and looks for the run carrying that hash — never a run id written
        # into the repository, and never an implicit "most recent run" rule (FR-061).
        "brief_sha256": brief.content_sha256 if brief else None,
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


async def _timeline(session: AsyncSession, run_id: uuid.UUID) -> AsyncIterator[SSEEvent]:
    """Replays everything the run has already done, then follows it live.

    Starting from the epoch rather than from connection time is deliberate: a console that
    connects late, or reconnects after a redeploy, still sees the whole timeline.
    """
    since = dict.fromkeys((kind for kind, _ in _SOURCES), datetime.min.replace(tzinfo=UTC))

    while True:
        emitted = False
        for kind, sql in _SOURCES:
            rows = (
                await session.execute(text(sql), {"run_id": run_id, "since": since[kind]})
            ).mappings().all()
            for row in rows:
                since[kind] = row["at"]
                data = {key: value for key, value in row.items() if key != "at"}
                yield SSEEvent(kind=kind, data=data | {"at": row["at"].isoformat()})
                emitted = True

        status = (
            await session.execute(
                text("SELECT status FROM runs WHERE id = :run_id"), {"run_id": run_id}
            )
        ).scalar_one_or_none()
        # A finished run has a finite timeline; drain it, then let the stream close.
        if status != "running" and not emitted:
            return

        await session.commit()  # release the snapshot, or the next poll re-reads this one
        await asyncio.sleep(POLL_SECONDS)


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "run not found"}
        )
    return sse_response(_timeline(session, run_id))
