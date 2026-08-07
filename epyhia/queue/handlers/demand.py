import uuid

from sqlalchemy.ext.asyncio import AsyncSession

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


async def handle_demand(session: AsyncSession, task: Task) -> None:
    """Write the pack, then queue the render.

    Nothing here goes outbound. Publishing a post and sending the launch email are gated
    actions with their own approval, and they are not this handler's to request.
    """
    run = await session.get(Run, task.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id)
    brief = await session.get(Brief, run.brief_id)

    for deliverable in DELIVERABLES:
        await produce(
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


register_handler("demand", handle_demand)
