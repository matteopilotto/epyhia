from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epyhia.config import settings


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _session_factory()() as session:
        yield session
