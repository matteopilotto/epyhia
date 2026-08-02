import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.config import settings


@pytest_asyncio.fixture
async def queue_session() -> AsyncIterator[AsyncSession]:
    """A real, committing session against `tasks`/`runs`/`briefs`.

    Queue tests need genuine cross-session durability (two workers racing a real claim
    statement), which the transactional `db_session` fixture cannot exercise. Isolation
    between tests comes from truncating, not from a rolled-back transaction.
    """
    engine = create_async_engine(
        settings.database_url or "postgresql+asyncpg://epyhia:epyhia@localhost:5432/epyhia"
    )
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE tasks, runs, briefs CASCADE"))

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE tasks, runs, briefs CASCADE"))
        await engine.dispose()


async def make_run(session: AsyncSession) -> uuid.UUID:
    """Insert the minimal brief + run a `tasks.run_id` FK requires."""
    brief_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO briefs (id, payload, content_sha256, guardrail_decision, guardrail_model) "
            "VALUES (:id, '{}'::jsonb, :hash, 'pass', 'test-model')"
        ),
        {"id": brief_id, "hash": str(uuid.uuid4())},
    )
    run_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO runs (id, brief_id, prompt_version, grounding_set, budget_usd, "
            "spend_usd, status, alias) "
            "VALUES (:id, :brief_id, 'v1', '{}'::jsonb, 25, 0, 'running', :alias)"
        ),
        {"id": run_id, "brief_id": brief_id, "alias": f"epyhia-{run_id.hex[:12]}.vercel.app"},
    )
    await session.commit()
    return run_id
