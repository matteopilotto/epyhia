from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.agents.strategist import run_strategist
from epyhia.models.briefs import Brief
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.pipeline import enqueue_stages
from epyhia.queue.worker import register_handler


async def handle_plan(session: AsyncSession, task: Task) -> None:
    """Run the Strategist, then materialise the stages it selected as task rows."""
    run = await session.get(Run, task.run_id)
    brief = await session.get(Brief, run.brief_id)

    deps = await run_strategist(
        session,
        run_id=run.id,
        brief_id=brief.id,
        brief_payload=brief.payload,
        task_id=task.id,
    )
    await enqueue_stages(session, run_id=run.id, stages=deps.selected_stages)


register_handler("plan", handle_plan)
