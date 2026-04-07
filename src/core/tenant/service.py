"""Tenant lifecycle management: provisioning, module activation, and queries."""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError, NotFoundError, TenantNotFoundError
from src.core.tenant.models import Tenant, TenantModule

logger = logging.getLogger(__name__)


class TenantService:
    """Manages tenant provisioning, schema creation, and module activation."""

    async def provision_tenant(
        self,
        slug: str,
        name: str,
        db: AsyncSession,
        subscription_tier: str = "free",
    ) -> Tenant:
        """Create a new tenant record and its isolated PostgreSQL schema.

        Steps:
            1. Check slug uniqueness
            2. Insert tenant record in public schema
            3. Create the PostgreSQL schema ``tenant_{slug}``

        Args:
            slug: Unique tenant identifier (used as schema name suffix).
            name: Display name for the tenant / company.
            db: Async session scoped to the public schema.
            subscription_tier: Subscription level (default: 'free').

        Returns:
            The newly created Tenant instance.

        Raises:
            ConflictError: If a tenant with this slug already exists.
        """
        existing = await db.execute(
            select(Tenant).where(Tenant.slug == slug)
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError(f"Tenant with slug '{slug}' already exists")

        tenant = Tenant(
            slug=slug,
            name=name,
            subscription_tier=subscription_tier,
        )
        db.add(tenant)
        await db.flush()

        schema_name = f"tenant_{slug}"
        await db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))

        # Run tenant-schema migrations to create module tables
        try:
            from migrations.env import migrate_tenant_async
            await migrate_tenant_async(slug)
            logger.info("Tenant schema migrations applied for '%s'", slug)
        except Exception:
            logger.warning(
                "Tenant schema migrations skipped for '%s' "
                "(no tenant migrations found yet)",
                slug,
                exc_info=True,
            )

        return tenant

    async def deactivate_tenant(self, tenant_id: uuid.UUID, db: AsyncSession) -> Tenant:
        """Mark a tenant as inactive.

        Args:
            tenant_id: The UUID of the tenant to deactivate.
            db: Async session scoped to the public schema.

        Returns:
            The updated Tenant instance.

        Raises:
            TenantNotFoundError: If no tenant with this ID exists.
        """
        tenant = await self._get_tenant_or_raise(tenant_id, db)
        tenant.is_active = False
        await db.flush()
        return tenant

    async def activate_module(
        self,
        tenant_id: uuid.UUID,
        module_name: str,
        db: AsyncSession,
    ) -> TenantModule:
        """Activate a module for a given tenant.

        If the module was previously deactivated, it will be re-activated.
        If it was never activated, a new record is created.

        Args:
            tenant_id: The UUID of the tenant.
            module_name: The registry name of the module (e.g. 'contacts').
            db: Async session scoped to the public schema.

        Returns:
            The TenantModule record (new or re-activated).

        Raises:
            TenantNotFoundError: If the tenant does not exist.
        """
        await self._get_tenant_or_raise(tenant_id, db)

        result = await db.execute(
            select(TenantModule).where(
                TenantModule.tenant_id == tenant_id,
                TenantModule.module_name == module_name,
            )
        )
        tenant_module = result.scalar_one_or_none()

        if tenant_module is not None:
            tenant_module.is_active = True
            tenant_module.activated_at = datetime.now(timezone.utc)
            await db.flush()
            return tenant_module

        tenant_module = TenantModule(
            tenant_id=tenant_id,
            module_name=module_name,
        )
        db.add(tenant_module)
        await db.flush()
        return tenant_module

    async def deactivate_module(
        self,
        tenant_id: uuid.UUID,
        module_name: str,
        db: AsyncSession,
    ) -> TenantModule:
        """Deactivate a module for a given tenant.

        Args:
            tenant_id: The UUID of the tenant.
            module_name: The registry name of the module.
            db: Async session scoped to the public schema.

        Returns:
            The updated TenantModule record.

        Raises:
            NotFoundError: If the module was never activated for this tenant.
        """
        result = await db.execute(
            select(TenantModule).where(
                TenantModule.tenant_id == tenant_id,
                TenantModule.module_name == module_name,
            )
        )
        tenant_module = result.scalar_one_or_none()

        if tenant_module is None:
            raise NotFoundError("TenantModule", f"{tenant_id}:{module_name}")

        tenant_module.is_active = False
        await db.flush()
        return tenant_module

    async def get_active_modules(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[str]:
        """Return the list of active module names for a tenant.

        Args:
            tenant_id: The UUID of the tenant.
            db: Async session scoped to the public schema.

        Returns:
            A list of active module name strings.
        """
        result = await db.execute(
            select(TenantModule.module_name).where(
                TenantModule.tenant_id == tenant_id,
                TenantModule.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def _get_tenant_or_raise(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> Tenant:
        """Load a tenant by ID or raise TenantNotFoundError."""
        result = await db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise TenantNotFoundError(str(tenant_id))
        return tenant
