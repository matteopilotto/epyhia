import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import logfire
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia import observability
from epyhia.config import settings

_REPO_ROOT = Path(__file__).resolve().parent.parent

# The suite must never ship spans. `send_to_logfire="if-token-present"` protects CI, which
# has no token; it does not protect a developer who has just put one in `.env`, because
# `load_dotenv()` puts it in the environment and the suite runs `create_app()` and
# `run_worker()` for real. Disabling the exporter and marking tracing already configured
# means neither of them can turn it back on and post a test run to the live project.
logfire.configure(send_to_logfire=False)
observability._configured = True


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


@pytest.fixture(autouse=True)
def _collapse_verify_backoff(request: pytest.FixtureRequest, monkeypatch) -> None:
    """Run the gate's verify schedule at zero wall clock.

    Every test here asserts attempt *counts*, never elapsed time, so the seconds the gate
    waits in production would be pure suite latency. The one test that guards those
    production values opts out with `@pytest.mark.realistic_backoff`.
    """
    if "realistic_backoff" in request.keywords:
        return
    from epyhia.gate import gate

    monkeypatch.setattr(gate, "VERIFY_BACKOFF_BASE_SECONDS", 1.0)
    monkeypatch.setattr(gate, "VERIFY_BACKOFF_CAP_SECONDS", 0.001)


@pytest.fixture(autouse=True)
def _site_review_loop_offline(monkeypatch) -> None:
    """The site stage's review loop reaches neither a browser nor a provider by default.

    Two things in that loop are not covered by a test overriding `web_builder.agent`. The
    screenshot step resolves a Chromium binary and would find the developer's own Chrome, then
    render every page the suite builds, twice, at real wall clock. The revision pass is a
    second agent instance, so a page with lint findings would reach the real model — and
    `load_dotenv()` means the key in `.env` is present while the suite runs. CI must need
    neither a browser nor a key.

    Both are patched to the failure they already have to survive: unavailable renders and a
    revision that did not produce a page are recorded skips, never a failed run (FR-015). The
    tests that exercise a successful capture or a real revision opt back in.
    """
    from epyhia.design.screenshot import Screenshots
    from epyhia.queue.handlers import site

    async def unavailable(html: str) -> Screenshots:
        return Screenshots.missing("no chromium binary in the test environment")

    async def unreachable(*args, **kwargs) -> str:
        raise AssertionError("the revision pass is not overridden in this test")

    monkeypatch.setattr(site, "capture", unavailable)
    monkeypatch.setattr(site, "revise_site", unreachable)


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
