import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.artifacts import Artifact
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.handlers.pack import produce
from epyhia.queue.worker import register_handler

# The marketing pack, in the order it is written. Each is drafted, checked and revised by
# the same loop the landing copy goes through — one artifact per deliverable, clean or
# flagged (FR-021, FR-024).
DELIVERABLES = ("posts", "email", "video_props")


async def existing_task_slots(session: AsyncSession, run_id: uuid.UUID, kind: str) -> set:
    """The `slot`s (or `None`, for a slot-less kind) this run already has a task for — the
    idempotency guard the fan-out needs and `video`'s single row never did, since a duplicate
    `publish` task would park on an action whose `task_id` names the first task and never
    settle (§1 of the outreach plan). Shared with `scripts/backfill_outreach.py`, which
    enqueues the same rows against already-processed runs."""
    rows = (
        await session.execute(select(Task.payload).where(Task.run_id == run_id, Task.kind == kind))
    ).scalars()
    return {(row or {}).get("slot") for row in rows}


async def handle_demand(session: AsyncSession, task: Task) -> None:
    """Write the pack, then queue the render and the outreach it feeds.

    Nothing here goes outbound itself. Publishing a post and sending the launch email are
    gated actions with their own approval, requested by the outreach tasks this handler
    enqueues below — not by this handler directly.
    """
    run = await session.get(Run, task.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id)
    brief = await session.get(Brief, run.brief_id)

    artifacts: dict[str, Artifact] = {}
    for deliverable in DELIVERABLES:
        artifacts[deliverable] = await produce(
            session,
            run_id=run.id,
            deliverable=deliverable,
            brand_doc=brand_doc.doc,
            brief=brief.payload,
            grounding_set=run.grounding_set,
            task_id=task.id,
        )

    # Enqueued whether or not the props came out clean. The refusal to render flagged props
    # already lives in exactly one place — `video.handle_video` — and duplicating it here
    # would be the same mistake the site handler's guard exists to fix, in reverse: a failed
    # `video` task carrying "video_props artifact is flagged, not clean" is a named, readable
    # refusal, whereas a task that was never created is invisible (FR-024).
    #
    # No `depends_on` and no pipeline edge: this row is written in the same transaction that
    # commits the `video_props` artifact and this task's `done`, so there is no race for an
    # edge to guard against, and `video` stays handler-enqueued rather than Strategist-
    # selectable.
    session.add(Task(id=uuid.uuid4(), run_id=run.id, kind="video", state="pending"))

    # Launch announcements go out only after the site is live — `depends_on` is `_CLAIM_SQL`'s
    # ordering, for free. A missing `site` task (none of the pipeline's business here) leaves
    # outreach undependent rather than unreachable.
    site_task_id = (
        await session.execute(
            select(Task.id).where(Task.run_id == run.id, Task.kind == "site")
        )
    ).scalar_one_or_none()
    depends_on = [site_task_id] if site_task_id is not None else None

    posts = json.loads(artifacts["posts"].bytes)["posts"]
    existing_publish_slots = await existing_task_slots(session, run.id, "publish")
    for slot in range(len(posts)):
        if slot in existing_publish_slots:
            continue
        session.add(
            Task(
                id=uuid.uuid4(),
                run_id=run.id,
                kind="publish",
                state="pending",
                payload={"slot": slot},
                depends_on=depends_on,
            )
        )

    if None not in await existing_task_slots(session, run.id, "send_email"):
        session.add(
            Task(
                id=uuid.uuid4(),
                run_id=run.id,
                kind="send_email",
                state="pending",
                depends_on=depends_on,
            )
        )


register_handler("demand", handle_demand)
