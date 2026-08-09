from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.gate import registry
from tests.conftest import test_database_url

# `agent_cache` has no FK to anything, so `CASCADE` from `runs` does not reach it — and a
# memo left behind by an earlier test would serve the next one's generation, changing its
# `agent_calls` rows. Droppable at any time is exactly what makes truncating it safe.
_TABLES = "actions, artifacts, agent_calls, tasks, runs, brand_docs, briefs, agent_cache"


@pytest_asyncio.fixture
async def integration_session() -> AsyncIterator[AsyncSession]:
    """A real, committing session across the whole schema.

    An integration test has to cross transactions the way the system does — the worker
    commits between stages and the gate commits at every transition — so the transactional
    `db_session` fixture cannot express it. Isolation comes from truncating.
    """
    engine = create_async_engine(test_database_url())
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_TABLES} CASCADE"))

    session = async_sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        registry.clear()
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await engine.dispose()
