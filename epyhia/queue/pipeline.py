import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from epyhia.models.tasks import Task

# The pipeline, in code. `plan` is the task already running when this is consulted; it fans
# out into copy → site, with demand and money in parallel (contracts/agent-io.md, FR-013).
#
# The Strategist selects which of these stages a run needs. It cannot add a stage, remove an
# edge, or reorder one, because the edges are read from here and never from what it returned
# — orchestration a model invents per run would mean idempotency keys computed over work
# whose existence is itself uncertain (§3.3, Principle III).
#
# Insertion order is topological, so iterating this mapping yields dependencies first.
STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "copy": (),
    "site": ("copy",),
    "demand": (),
    "money": (),
}


def resolve_stages(selected: list[str]) -> list[str]:
    """The selection, closed over the fixed dependency edges and returned in pipeline
    order. Selecting `site` therefore also runs `copy`: the copy artifact blocks the site
    (FR-021), and that is a property of the pipeline rather than of the selection."""
    wanted: set[str] = set()

    def add(stage: str) -> None:
        if stage in wanted:
            return
        wanted.add(stage)
        for dependency in STAGE_DEPENDENCIES[stage]:
            add(dependency)

    for stage in selected:
        add(stage)
    return [stage for stage in STAGE_DEPENDENCIES if stage in wanted]


async def enqueue_stages(
    session: AsyncSession, *, run_id: uuid.UUID, stages: list[str]
) -> dict[str, uuid.UUID]:
    """Write one `tasks` row per selected stage, wiring `depends_on` from the fixed edges.

    Only flushes — the caller owns the transaction, so the task rows land with whatever
    else the handler wrote.
    """
    task_ids: dict[str, uuid.UUID] = {}
    for stage in resolve_stages(stages):
        depends_on = [task_ids[dependency] for dependency in STAGE_DEPENDENCIES[stage]]
        task = Task(
            id=uuid.uuid4(),
            run_id=run_id,
            kind=stage,
            state="pending",
            depends_on=depends_on or None,
        )
        session.add(task)
        task_ids[stage] = task.id
    await session.flush()
    return task_ids
