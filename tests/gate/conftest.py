from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.gate import registry
from tests.conftest import test_database_url


@pytest_asyncio.fixture
async def gate_session() -> AsyncIterator[AsyncSession]:
    """A real, committing session against `actions`.

    Gate tests need genuine cross-session durability (an approval must survive a crash, a
    concurrent racer must see the winner's row) which the transactional `db_session` fixture
    cannot exercise, since it rolls back everything at teardown. Isolation between tests here
    comes from truncating `actions`, not from a rolled-back transaction.
    """
    engine = create_async_engine(test_database_url())
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE actions"))

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        registry.clear()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE actions"))
        await engine.dispose()


@pytest_asyncio.fixture
async def fresh_session(gate_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A second, independent session against the same database as `gate_session`."""
    engine = create_async_engine(test_database_url())
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()
