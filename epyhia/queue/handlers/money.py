from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents.ops import wire_catalogue
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import register_handler


async def handle_money(session: AsyncSession, task: Task) -> None:
    """The `money` stage: the run's resolved catalogue becomes a live processor catalogue,
    and stops at one approval before it can charge anyone.

    Nothing here touches the site. The buy button carries a slug derived at ingest, so this
    stage and the `site` stage read the same brief field and neither waits on the other
    (DESIGN.md §6.2).
    """
    run = await session.get(Run, task.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id)
    brief = await session.get(Brief, run.brief_id)

    await wire_catalogue(
        session,
        run=run,
        brief=brief,
        brand_doc=brand_doc.doc,
        task_id=task.id,
    )


register_handler("money", handle_money)
