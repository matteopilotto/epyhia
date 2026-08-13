import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.export.archive import build_pack
from epyhia.models.artifacts import Artifact
from epyhia.models.runs import Run

router = APIRouter(dependencies=[Depends(require_operator)])


@router.get("/runs/{run_id}/pack")
async def download_pack(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    """The run's deliverables as one archive, assembled here and never stored (FR-008).

    A run that has produced nothing answers with a valid archive whose manifest lists zero
    files — the in-progress case. A run that does not exist is a 404: the two are different
    answers and an empty zip would hide a mistyped id.
    """
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "run not found"}
        )

    result = await session.execute(
        select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.kind, Artifact.revision)
    )
    return Response(
        content=build_pack(run_id, result.scalars().all()),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="pack-{run_id}.zip"'},
    )
