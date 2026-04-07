"""Tenant-scoped database session that sets the PostgreSQL search_path."""

import re
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.session import AsyncSessionLocal

# Only allow safe slug characters to prevent SQL injection in SET search_path
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _validate_slug(slug: str) -> str:
    """Validate that a tenant slug is safe for use in a schema name.

    Raises ValueError if the slug contains unsafe characters.
    """
    if not _SLUG_PATTERN.match(slug):
        raise ValueError(f"Invalid tenant slug: {slug!r}")
    return slug


async def get_tenant_db(tenant_slug: str) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session with search_path set to the tenant's schema.

    This is the **only** session generator that module code should use.
    It ensures every query executes within the correct tenant schema.

    Args:
        tenant_slug: The tenant's unique slug (used as schema name suffix).

    Yields:
        An AsyncSession with search_path set to ``tenant_{slug}, public``.
    """
    safe_slug = _validate_slug(tenant_slug)
    schema_name = f"tenant_{safe_slug}"

    session = AsyncSessionLocal()
    try:
        await session.execute(text(f"SET search_path TO {schema_name}, public"))
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
