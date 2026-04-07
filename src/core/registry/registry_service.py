"""Runtime service for checking module activation per tenant.

This is used as a FastAPI dependency on every module route to enforce
that the current tenant has the requested module activated.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ModuleNotActiveError
from src.core.tenant.models import TenantModule


class RegistryService:
    """Checks module activation state against the ``tenant_modules`` table."""

    async def is_active(
        self,
        tenant_id: uuid.UUID,
        module_name: str,
        db: AsyncSession,
    ) -> bool:
        """Check whether a module is active for a given tenant.

        Args:
            tenant_id: The tenant's UUID.
            module_name: The module's registry name.
            db: Async session (public schema).

        Returns:
            True if the module is active, False otherwise.
        """
        result = await db.execute(
            select(TenantModule.is_active).where(
                TenantModule.tenant_id == tenant_id,
                TenantModule.module_name == module_name,
            )
        )
        is_active = result.scalar_one_or_none()
        return is_active is True

    async def require_module(
        self,
        tenant_id: uuid.UUID,
        module_name: str,
        db: AsyncSession,
    ) -> None:
        """Assert that a module is active for the tenant, or raise.

        Use this as a guard at the top of module routes via FastAPI
        ``Depends()`` to enforce module activation.

        Args:
            tenant_id: The tenant's UUID.
            module_name: The module's registry name.
            db: Async session (public schema).

        Raises:
            ModuleNotActiveError: If the module is not active (HTTP 403).
        """
        if not await self.is_active(tenant_id, module_name, db):
            raise ModuleNotActiveError(module_name)


registry_service = RegistryService()
