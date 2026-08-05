from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.handlers.pack import produce
from epyhia.queue.worker import register_handler


async def handle_copy(session: AsyncSession, task: Task) -> None:
    """The landing copy, written and reviewed exactly like the rest of the pack (FR-021).

    `site` depends on this task, so the Web Builder is handed words rather than the layout
    intent the interim stub could carry — which is the whole of what the stub could not do,
    and the reason it is gone (§3.4, §12 step 6).
    """
    run = await session.get(Run, task.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id)
    brief = await session.get(Brief, run.brief_id)

    await produce(
        session,
        run_id=run.id,
        deliverable="copy",
        brand_doc=brand_doc.doc,
        brief=brief.payload,
        grounding_set=run.grounding_set,
        task_id=task.id,
    )


register_handler("copy", handle_copy)
