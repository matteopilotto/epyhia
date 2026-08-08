import asyncio
import json
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.artifacts.store import PostgresArtifactStore
from epyhia.models.artifacts import Artifact
from epyhia.models.tasks import Task
from epyhia.queue.worker import register_handler

_store = PostgresArtifactStore()

VIDEO_ROOT = Path(__file__).resolve().parents[3] / "video"
ENTRY = "src/index.ts"

# Two cuts of one archetype from **one** props artifact (FR-025). Rendering the vertical cut
# from its own props would let the two films state different things, which is exactly the
# failure the single grounding-checked artifact exists to prevent.
CUTS = (("video", ""), ("video_vertical", "-vertical"))


class RenderFailed(Exception):
    """The render did not produce a file. The task fails and the sweeper decides whether it
    is worth another attempt (R8)."""


def composition_id(archetype_id: str, suffix: str) -> str:
    """Mirrors `compositionId` in `video/src/Root.tsx`: Remotion composition ids admit no
    underscores, and the archetype ids carry them. Derived on both sides rather than stored,
    so a new archetype needs no table here."""
    return archetype_id.replace("_", "-") + suffix


async def _render(composition: str, props_path: Path, out: Path) -> bytes:
    """A local render, so it spends nothing and sends nothing — which is why it does not go
    through the Action Gate (DESIGN.md §6.4). Publishing the result does."""
    process = await asyncio.create_subprocess_exec(
        "npx",
        "remotion",
        "render",
        ENTRY,
        composition,
        str(out),
        f"--props={props_path}",
        cwd=VIDEO_ROOT,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RenderFailed(f"{composition}: {stderr.decode('utf-8', 'replace')[-2000:]}")
    return out.read_bytes()


async def handle_video(session: AsyncSession, task: Task) -> None:
    """Render both cuts from the run's `video_props` artifact and store them.

    The rendered frames are never re-checked for numerals: the props are what carried the
    facts, and they were set-differenced before anything was rendered (research.md R5). A
    flagged props artifact is therefore not something to render and inspect afterwards —
    it is something that must not reach a frame at all (FR-026).
    """
    props_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.run_id == task.run_id, Artifact.kind == "video_props")
            .order_by(Artifact.revision.desc())
        )
    ).scalars().first()

    if props_artifact is None:
        raise RenderFailed("no video_props artifact for this run")
    if props_artifact.grounding_status != "clean":
        raise RenderFailed(
            f"video_props artifact is {props_artifact.grounding_status}, not clean"
        )

    props = json.loads(props_artifact.bytes)
    archetype = props["archetype_id"]

    # The MP4s of record live in Postgres, so the files exist only for as long as the render
    # needs them — a leftover in the tree would be a second, unversioned copy.
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        props_path = workspace / "props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

        for kind, suffix in CUTS:
            out = workspace / f"{kind}.mp4"
            content = await _render(composition_id(archetype, suffix), props_path, out)
            await _store.write(
                session,
                run_id=task.run_id,
                kind=kind,
                path=f"{kind}.mp4",
                content_type="video/mp4",
                content=content,
                grounding_status="clean",
            )


register_handler("video", handle_video)
