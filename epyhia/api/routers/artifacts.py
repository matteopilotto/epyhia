import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.api.auth import require_operator
from epyhia.api.db import get_session
from epyhia.models.artifacts import Artifact

router = APIRouter(dependencies=[Depends(require_operator)])

# Which artifacts carry their bytes inline. A rendered video is described rather than
# inlined; everything a violation can be read against is text.
_INLINE_TYPES = ("application/json", "text/")


def _summary(artifact: Artifact) -> dict:
    return {
        "id": artifact.id,
        "run_id": artifact.run_id,
        "kind": artifact.kind,
        "path": artifact.path,
        "content_type": artifact.content_type,
        "sha256": artifact.sha256,
        "size_bytes": len(artifact.bytes),
        # The whole point of the pair: a flagged artifact is listed with what is wrong with
        # it, itemised, rather than being hidden or silently dropped (FR-024).
        "grounding_status": artifact.grounding_status,
        "violations": artifact.violations,
        "revision": artifact.revision,
        "created_at": artifact.created_at,
    }


@router.get("/runs/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    """Every artifact the run produced, flagged ones included. Surfacing them is the remedy
    path — the failure this guards against is work disappearing quietly (FR-024)."""
    result = await session.execute(
        select(Artifact)
        .where(Artifact.run_id == run_id)
        .order_by(Artifact.created_at, Artifact.revision)
    )
    return [_summary(artifact) for artifact in result.scalars().all()]


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    """Read-only, deliberately: the fix for a flagged artifact is to correct the brief or the
    brand doc and re-run, never to edit the output into compliance (contracts/rest-api.md)."""
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "artifact not found"}
        )

    content = None
    if artifact.content_type.startswith(_INLINE_TYPES):
        content = artifact.bytes.decode("utf-8", "replace")
    return _summary(artifact) | {"content": content}


@router.get("/artifacts/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    """The stored bytes, unmodified — what the site preview, the video players and a
    single-artifact download are fed.

    It carries the same operator dependency as every other route rather than a signed URL or
    a token in a query string: `<video src>` cannot send an `Authorization` header, so the
    console fetches here and hands the elements a blob URL instead (FR-007, research R1).
    Byte-identity with the row is the contract — `sha256(body) == artifact.sha256`.
    """
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "detail": "artifact not found"}
        )

    return Response(
        content=artifact.bytes,
        media_type=artifact.content_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.path}"'},
    )
