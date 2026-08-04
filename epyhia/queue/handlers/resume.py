import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import epyhia.gate.adapters  # noqa: F401  — registers the adapter pairs
from epyhia.gate import gate
from epyhia.models.actions import Action
from epyhia.models.brand_docs import BrandDoc
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.worker import register_handler


async def handle_resume(session: AsyncSession, task: Task) -> None:
    """Carry a decided action through to its outcome.

    Everything needed is rebuilt from the `actions` row — nothing is replayed from whatever
    the process that paused was holding, because there is no such process any more (R7 step 6).
    """
    action_id = uuid.UUID(task.payload["action_id"])
    action = await session.get(Action, action_id)

    run = await session.get(Run, action.run_id)
    brand_doc = await session.get(BrandDoc, run.brand_doc_id) if run else None

    result = await gate.resume(
        session, action_id, brand_doc=brand_doc.doc if brand_doc else None
    )

    # Settle the task that parked at the pause, so a denied or failed action does not leave
    # its stage waiting for an approval that has already been decided.
    if action.task_id is not None:
        await session.execute(
            text("UPDATE tasks SET state = :state, error = :error WHERE id = :id"),
            {
                "state": "done" if result["state"] == "succeeded" else "failed",
                "error": result["error"],
                "id": action.task_id,
            },
        )
        await session.commit()


register_handler("resume", handle_resume)
