from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.config import settings
from epyhia.gate import registry

_TABLES = "actions, artifacts, agent_calls, tasks, runs, brand_docs, briefs"


@pytest_asyncio.fixture
async def integration_session() -> AsyncIterator[AsyncSession]:
    """A real, committing session across the whole schema.

    An integration test has to cross transactions the way the system does — the worker
    commits between stages and the gate commits at every transition — so the transactional
    `db_session` fixture cannot express it. Isolation comes from truncating.
    """
    engine = create_async_engine(
        settings.database_url or "postgresql+asyncpg://epyhia:epyhia@localhost:5432/epyhia"
    )
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
