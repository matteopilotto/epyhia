import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def settle_run(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Write the run's terminal status at the moment its last stage settles (T144).

    `runs.status` previously left `running` in one direction only — `halted_budget` — so a
    run whose every stage was `done` read `running` forever, its SSE timeline never closed,
    and the console's `succeeded` badge could never render. The stages are a DAG rather than
    a line, so terminal means **no stage can still move**: nothing pending, claimed, running
    or parked at an approval. Then every stage `done` is `succeeded`, and a `failed` stage
    among them is `failed` — which the operator's retry button (T142/T145) may yet re-open,
    which is why the writer lives at the task-settle points (the worker loop and the
    sweeper's past-the-cap failure) rather than in a periodic sweep that would race that
    button. The retry endpoint re-opens a settled run for the same reason.

    The guard on `status = 'running'` keeps `halted_budget` authoritative — a halted run
    stays halted — and keeps this a one-way write: settling never resurrects anything.
    The caller owns the transaction.
    """
    states = set(
        (
            await session.execute(
                text("SELECT DISTINCT state FROM tasks WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
        ).scalars()
    )
    if not states or states & {"pending", "claimed", "running", "awaiting_approval"}:
        return
    await session.execute(
        text("UPDATE runs SET status = :status WHERE id = :run_id AND status = 'running'"),
        {"status": "failed" if "failed" in states else "succeeded", "run_id": run_id},
    )
