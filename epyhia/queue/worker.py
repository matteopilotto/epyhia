import asyncio
import logging
from collections.abc import Awaitable, Callable

from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.config import settings
from epyhia.models.tasks import Task
from epyhia.queue.claim import claim_task

logger = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, Task], Awaitable[None]]

# kind -> handler, populated by each `epyhia.queue.handlers.*` module as it lands.
HANDLERS: dict[str, Handler] = {}


def register_handler(kind: str, handler: Handler) -> None:
    HANDLERS[kind] = handler


async def run_once(session: AsyncSession, *, kind: str | None = None) -> bool:
    """Claim and dispatch one task. Returns False if there was nothing to claim.

    A handler that raises `ApprovalRequired` (R7 step 4) parks the task `awaiting_approval`
    with the action id on its payload and releases the lease — no process holds state
    across a human's pause. Any other exception rolls back and re-raises, leaving the task
    `running` for the sweeper to expire.
    """
    task = await claim_task(session, kind=kind)
    await session.commit()
    if task is None:
        return False

    handler = HANDLERS.get(task.kind)
    if handler is None:
        raise RuntimeError(f"no handler registered for task kind: {task.kind!r}")

    await session.execute(
        text("UPDATE tasks SET state = 'running' WHERE id = :id"), {"id": task.id}
    )
    await session.commit()

    try:
        await handler(session, task)
    except ApprovalRequired as exc:
        action_id = (exc.metadata or {}).get("action_id")
        await session.execute(
            text(
                "UPDATE tasks SET state = 'awaiting_approval', lease_expires_at = NULL, "
                "payload = COALESCE(payload, '{}'::jsonb) "
                "|| jsonb_build_object('action_id', CAST(:action_id AS text)) "
                "WHERE id = :id"
            ),
            {"id": task.id, "action_id": action_id},
        )
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        raise

    await session.commit()
    return True


async def run_worker(*, poll_interval_seconds: float = 1.0) -> None:
    """The `worker` Fly process entrypoint (fly.toml `[processes] worker`)."""
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        while True:
            async with session_factory() as session:
                claimed = await run_once(session)
            if not claimed:
                await asyncio.sleep(poll_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker())
