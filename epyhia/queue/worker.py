import asyncio
import logging
from collections.abc import Awaitable, Callable

from pydantic_ai.exceptions import ApprovalRequired
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.config import settings
from epyhia.cost.budget import HALTED, enforce_run_budget
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
    across a human's pause.

    Any other exception rolls the handler's writes back and lands the task `failed` with
    the reason on the row. It must not leave the loop: a worker that dies on one task stops
    serving every other run, and the failure a crash leaves behind is a task stuck `running`
    against a lease nothing sweeps — invisible in exactly the way a `failed` row naming its
    reason is not.
    """
    task = await claim_task(session, kind=kind)
    await session.commit()
    if task is None:
        return False

    # A halted run stops starting new work (FR-053). `resume` is exempt on purpose: it drives
    # an action the gate already began, and halting must not leave a side effect in the world
    # with no probe run against it.
    if task.kind != "resume" and await enforce_run_budget(session, task.run_id):
        await session.execute(
            text(
                "UPDATE tasks SET state = 'failed', lease_expires_at = NULL, error = :error "
                "WHERE id = :id"
            ),
            {"id": task.id, "error": f"run halted: spend reached budget ({HALTED})"},
        )
        await session.commit()
        return True

    await session.execute(
        text("UPDATE tasks SET state = 'running' WHERE id = :id"), {"id": task.id}
    )
    await session.commit()

    try:
        handler = HANDLERS.get(task.kind)
        if handler is None:
            raise RuntimeError(f"no handler registered for task kind: {task.kind!r}")
        await handler(session, task)
        await session.execute(
            text(
                "UPDATE tasks SET state = 'done', lease_expires_at = NULL WHERE id = :id"
            ),
            {"id": task.id},
        )
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
    except Exception as exc:
        # The rollback discards whatever the handler had written, so a task that failed
        # half-way leaves no artifact behind; the state change is written after it, on a
        # clean session, and is the only thing that survives.
        await session.rollback()
        logger.exception("task %s (%s) failed", task.id, task.kind)
        await session.execute(
            text(
                "UPDATE tasks SET state = 'failed', lease_expires_at = NULL, error = :error "
                "WHERE id = :id"
            ),
            {"id": task.id, "error": f"{type(exc).__name__}: {exc}"},
        )
        await session.commit()
        return True

    await session.commit()
    # Whatever this task spent is now on the run's row, so the next claim decides against a
    # current number rather than the one that was true a stage ago.
    await enforce_run_budget(session, task.run_id)
    return True


async def run_worker(*, poll_interval_seconds: float = 1.0) -> None:
    """The `worker` Fly process entrypoint (fly.toml `[processes] worker`)."""
    # Imported here rather than at module scope: each handler module registers itself by
    # calling `register_handler` above, so importing the package from the top would close
    # a cycle back onto this one.
    import epyhia.queue.handlers  # noqa: F401

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
    # `python -m epyhia.queue.worker` (docker-compose, fly.toml `[processes] worker`) loads
    # this file as `__main__`, and every handler module imports it again under its real name
    # to call `register_handler` — two module objects, two `HANDLERS` dicts. Dispatching from
    # the one `__main__` holds means dispatching from an empty registry, so the first task
    # claimed raises `no handler registered`. Run the loop that owns the registry the
    # handlers wrote into, not this file's copy of it.
    from epyhia.queue.worker import run_worker as _run_worker

    asyncio.run(_run_worker())
