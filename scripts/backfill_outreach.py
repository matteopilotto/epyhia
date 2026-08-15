"""Enqueue outreach (`publish` + `send_email`) for runs whose pack was produced before the
outreach wiring landed — the already-processed briefs; see
`.claude/plans/outreach-wiring-publish-send-email.md` §5.

    uv run python -m scripts.backfill_outreach [<run_id> ...]

No run ids: every run in the database. Given run ids: only those. Safe to run twice — the
same `(run_id, kind, slot)` existence guard `handle_demand`'s fan-out uses means a second
invocation enqueues nothing new (§1).

Not an Alembic migration: enqueueing outbound work that will page an operator for approval
is an operator decision, not a schema deploy side effect. This spends nothing itself — both
adapters declare `cost_usd = 0` — only the approval clicks that follow do.
"""

import argparse
import asyncio
import json
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.config import settings
from epyhia.cost.budget import HALTED
from epyhia.models.artifacts import Artifact
from epyhia.models.runs import Run
from epyhia.models.tasks import Task
from epyhia.queue.handlers.demand import existing_task_slots


async def _newest(session: AsyncSession, run_id: uuid.UUID, kind: str) -> Artifact | None:
    """Newest generation, not highest revision — the same lookup `handle_site` and
    `handle_video` use, so a re-run's fresh clean artifact is the one this reads."""
    return (
        await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id, Artifact.kind == kind)
            .order_by(Artifact.created_at.desc(), Artifact.revision.desc())
        )
    ).scalars().first()


async def backfill_run(session: AsyncSession, run: Run) -> dict:
    """Enqueue this run's missing outreach tasks and re-open it if it had already settled.

    Never raises for a run this skips — a run with no clean pack, or one halted on budget,
    is reported and left alone rather than stopping the rest of the backfill.
    """
    posts_artifact = await _newest(session, run.id, "posts")
    email_artifact = await _newest(session, run.id, "email")
    if posts_artifact is None or posts_artifact.grounding_status != "clean":
        return {"run_id": run.id, "skipped": "no clean posts artifact"}
    if email_artifact is None or email_artifact.grounding_status != "clean":
        return {"run_id": run.id, "skipped": "no clean email artifact"}
    if run.status == HALTED:
        return {"run_id": run.id, "skipped": "run is halted on budget"}

    # Harmless on these runs — `site` is already `done` — and keeping one code path with
    # `handle_demand`'s fan-out is worth more than the edge these rows will never enforce.
    site_task_id = (
        await session.execute(
            select(Task.id).where(Task.run_id == run.id, Task.kind == "site")
        )
    ).scalar_one_or_none()
    depends_on = [site_task_id] if site_task_id is not None else None

    posts = json.loads(posts_artifact.bytes)["posts"]
    existing_publish = await existing_task_slots(session, run.id, "publish")
    publish_enqueued = 0
    for slot in range(len(posts)):
        if slot in existing_publish:
            continue
        session.add(
            Task(
                id=uuid.uuid4(),
                run_id=run.id,
                kind="publish",
                state="pending",
                payload={"slot": slot},
                depends_on=depends_on,
            )
        )
        publish_enqueued += 1

    send_email_enqueued = 0
    if None not in await existing_task_slots(session, run.id, "send_email"):
        session.add(
            Task(
                id=uuid.uuid4(),
                run_id=run.id,
                kind="send_email",
                state="pending",
                depends_on=depends_on,
            )
        )
        send_email_enqueued = 1

    # Re-opened exactly as `POST /tasks/{id}/retry` re-opens a settled run (T144): the
    # operator's re-queue is a statement that the run is not finished after all, and the run
    # settles again once its outreach decides.
    reopened = run.status in ("succeeded", "failed")
    if reopened:
        run.status = "running"

    await session.commit()
    return {
        "run_id": run.id,
        "publish_enqueued": publish_enqueued,
        "send_email_enqueued": send_email_enqueued,
        "reopened": reopened,
    }


async def backfill(session: AsyncSession, run_ids: list[uuid.UUID] | None = None) -> list[dict]:
    stmt = select(Run)
    if run_ids:
        stmt = stmt.where(Run.id.in_(run_ids))
    runs = (await session.execute(stmt)).scalars().all()
    return [await backfill_run(session, run) for run in runs]


async def main(run_ids: list[uuid.UUID]) -> int:
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
            results = await backfill(session, run_ids or None)
    finally:
        await engine.dispose()

    if not results:
        print("no runs matched", file=sys.stderr)
        return 1

    for result in results:
        print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=uuid.UUID, nargs="*")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.run_id)))
