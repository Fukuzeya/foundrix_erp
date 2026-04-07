"""Alembic environment configuration for multi-tenant schema migrations.

This env.py supports two migration modes:

1. **Public schema migrations** (default):
   Run with ``alembic upgrade head`` — creates/updates shared tables
   (tenants, users, roles, permissions, etc.) in the public schema.

2. **Tenant schema migrations**:
   Run programmatically via ``migrate_tenant(slug)`` — applies tenant-specific
   tables (partners, invoices, etc.) to a single tenant's schema.
   Called by ``TenantService.provision_tenant()`` when onboarding new tenants.

The migration scripts themselves live in:
- ``migrations/public/``  — for public schema (version_locations)
- ``migrations/tenant/``  — for tenant schemas (used by migrate_tenant)
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import Connection, create_engine, pool, text

# ── Make sure src is importable ──────────────────────────────────────
# When Alembic runs as a CLI tool, the project root may not be on sys.path.
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.config import settings
from src.core.database.base import Base

# Import ALL models so that Base.metadata is fully populated.
# Alembic needs to see every model to auto-generate migrations.
from src.core.tenant.models import Tenant, TenantModule  # noqa: F401
from src.core.auth.models import (  # noqa: F401
    AuditLog,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserTenantRole,
)
from src.core.notifications.models import Notification  # noqa: F401
from src.core.webhooks.models import WebhookEndpoint, WebhookDelivery  # noqa: F401

logger = logging.getLogger("alembic.env")

# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Override sqlalchemy.url from Settings (never rely on alembic.ini value).
# Replace async driver with sync driver for Alembic (it uses sync connections).
sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2").replace(
    "postgresql://", "postgresql+psycopg2://"
)
config.set_main_option("sqlalchemy.url", sync_url)

# The MetaData object for autogenerate support.
target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """Filter which objects Alembic should include in autogenerate.

    For public migrations: include only objects in the 'public' schema.
    For tenant migrations: include only objects WITHOUT a schema (tenant-local).
    """
    schema_mode = os.environ.get("ALEMBIC_SCHEMA_MODE", "public")

    if type_ == "table":
        table_schema = getattr(object, "schema", None)
        if schema_mode == "public":
            return table_schema == "public"
        elif schema_mode == "tenant":
            return table_schema is None
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates a database connection and runs migrations within a transaction.
    """
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()


# ── Tenant Migration API ─────────────────────────────────────────────
# Used programmatically by TenantService.provision_tenant()


def migrate_tenant_sync(slug: str, connection: Connection) -> None:
    """Run tenant-schema migrations for a single tenant using a sync connection.

    Sets the search_path to the tenant's schema, then runs all migration
    scripts from the ``migrations/tenant/`` directory.

    Args:
        slug: The tenant's slug (schema name will be ``tenant_{slug}``).
        connection: An active synchronous SQLAlchemy connection.
    """
    schema_name = f"tenant_{slug}"

    # Ensure schema exists
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
    connection.execute(text(f"SET search_path TO {schema_name}"))

    # Configure Alembic to use tenant migration scripts
    tenant_versions_dir = str(Path(__file__).parent / "tenant")
    os.environ["ALEMBIC_SCHEMA_MODE"] = "tenant"

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        version_table="alembic_version",
        version_table_schema=schema_name,
    )

    with context.begin_transaction():
        context.run_migrations()

    # Reset
    connection.execute(text("SET search_path TO public"))
    os.environ.pop("ALEMBIC_SCHEMA_MODE", None)


def migrate_tenant(slug: str) -> None:
    """Run tenant-schema migrations for a single tenant.

    Creates a sync database connection, sets the search_path, and runs
    all tenant migrations. Called by ``TenantService.provision_tenant()``.

    Args:
        slug: The tenant's slug (schema name will be ``tenant_{slug}``).
    """
    engine = create_engine(sync_url, poolclass=pool.NullPool)

    with engine.connect() as connection:
        migrate_tenant_sync(slug, connection)
        connection.commit()

    engine.dispose()


async def migrate_tenant_async(slug: str) -> None:
    """Async wrapper for tenant migration.

    Runs the sync migration in a thread pool to avoid blocking the
    event loop.

    Args:
        slug: The tenant's slug.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, migrate_tenant, slug)
