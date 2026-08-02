import hashlib
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.artifacts import Artifact


class ArtifactStore(Protocol):
    async def write(
        self,
        session: AsyncSession,
        *,
        run_id: uuid.UUID,
        kind: str,
        path: str,
        content_type: str,
        content: bytes,
        grounding_status: str,
        violations: dict | list | None = None,
        revision: int = 0,
    ) -> Artifact: ...

    async def read(self, session: AsyncSession, artifact_id: uuid.UUID) -> Artifact | None: ...


class PostgresArtifactStore:
    """Writes artifact bytes into the `artifacts` table's `bytea` column (data-model.md
    "artifacts", DESIGN.md §5.4). Only `add`s and `flush`es — the caller owns the session
    and its commit, so an artifact lands in the same transaction as the task row that
    produced it.
    """

    async def write(
        self,
        session: AsyncSession,
        *,
        run_id: uuid.UUID,
        kind: str,
        path: str,
        content_type: str,
        content: bytes,
        grounding_status: str,
        violations: dict | list | None = None,
        revision: int = 0,
    ) -> Artifact:
        artifact = Artifact(
            run_id=run_id,
            kind=kind,
            path=path,
            content_type=content_type,
            bytes=content,
            sha256=hashlib.sha256(content).hexdigest(),
            grounding_status=grounding_status,
            violations=violations,
            revision=revision,
        )
        session.add(artifact)
        await session.flush()
        return artifact

    async def read(self, session: AsyncSession, artifact_id: uuid.UUID) -> Artifact | None:
        return await session.get(Artifact, artifact_id)
