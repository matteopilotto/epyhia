from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents.copy_stub import write_copy_stub
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import register_handler


async def handle_copy(session: AsyncSession, task: Task) -> None:
    """Interim: the stub fills this stage until the Marketer does (T077)."""
    run = await session.get(Run, task.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id)
    brief = await session.get(Brief, run.brief_id)

    await write_copy_stub(
        session,
        run_id=run.id,
        brand_doc=brand_doc.doc,
        grounding_set=run.grounding_set,
        locale=brief.payload["locale"],
    )


register_handler("copy", handle_copy)
