import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.config import settings

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_database_url() -> str:
    """The database every test engine points at — never the application's own.

    The suite truncates whole tables, so pointing it at `DATABASE_URL` destroys the runs of
    record. A misconfiguration here is unrecoverable, so it refuses rather than skips.
    """
    url = settings.test_database_url or "postgresql+asyncpg://epyhia:epyhia@localhost:5432/epyhia_test"
    if url == settings.database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is the application database; the test suite truncates it. "
            "Point TEST_DATABASE_URL at a separate database."
        )
    return url


@pytest.fixture(scope="session", autouse=True)
def test_schema() -> None:
    """Bring the test database up to head once per session.

    A subprocess, because `migrations/env.py` reads the URL from `epyhia.config.settings` at
    import time — and `load_dotenv()` never overrides an already-set variable, so the
    override below wins in the child.
    """
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=_REPO_ROOT,
        env={**os.environ, "DATABASE_URL": test_database_url()},
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """One connection per test, wrapped in a transaction that is always rolled back."""
    engine = create_async_engine(test_database_url())
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
