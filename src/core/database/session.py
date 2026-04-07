"""Async engine, session factory, and public-schema database dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=(not settings.is_production),
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_raw_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session scoped to the public schema.

    Use this only for operations on shared tables (tenants, users, etc.).
    Module code should never call this directly — use get_tenant_db instead.
    """
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
