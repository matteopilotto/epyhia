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


async def _settle(
    session: AsyncSession, task_id: uuid.UUID | None, *, state: str, error: str | None
) -> None:
    """Release the task that parked at the pause.

    Unconditional, because the pause is one-way: the decision is already on the action row,
    so a second operator click gets `not_awaiting_approval` and the sweeper leaves
    `awaiting_approval` alone. A stage left parked here is parked for good.
    """
    if task_id is None:
        return
    await session.execute(
        text("UPDATE tasks SET state = :state, error = :error WHERE id = :id"),
        {"state": state, "error": error, "id": task_id},
    )
    await session.commit()


async def handle_resume(session: AsyncSession, task: Task) -> None:
    """Carry a decided action through to its outcome.

    Everything needed is rebuilt from the `actions` row — nothing is replayed from whatever
    the process that paused was holding, because there is no such process any more (R7 step 6).
    The gate handles are plain typed calls rather than a deferred PydanticAI toolset, so what
    gets rebuilt is the gate's own context: the action, its run, and that run's brand doc.
    """
    action_id = uuid.UUID(task.payload["action_id"])
    action = await session.get(Action, action_id)

    run = await session.get(Run, action.run_id)
    brand_doc = (
        await session.get(BrandDoc, run.brand_doc_id) if run and run.brand_doc_id else None
    )

    try:
        result = await gate.resume(
            session, action_id, brand_doc=brand_doc.doc if brand_doc else None
        )
    except Exception as exc:
        # The gate has already written `failed` to the action and re-raised. Settling the
        # parked stage before the exception leaves this handler is what keeps an approved
        # action whose `execute()` threw from stranding its run at a pause nobody can clear.
        await _settle(session, action.task_id, state="failed", error=f"{type(exc).__name__}: {exc}")
        raise

    await _settle(
        session,
        action.task_id,
        state="done" if result["state"] == "succeeded" else "failed",
        error=result["error"],
    )


register_handler("resume", handle_resume)
