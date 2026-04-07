"""Seed data runner for initial platform setup and development data.

Modules register seed functions that are executed in dependency order
during initial setup or when a new tenant is provisioned.

Usage::

    # Register a seed function:
    @seed_runner.register("contacts", priority=10)
    async def seed_contacts(db: AsyncSession, tenant_id: uuid.UUID | None = None):
        # Create default contact categories, etc.
        ...

    # Run all seeds:
    await seed_runner.run_all(db)

    # Run tenant-specific seeds:
    await seed_runner.run_for_tenant(db, tenant_id)
"""

import logging
import uuid
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SeedFn = Callable[..., Awaitable[None]]


class _SeedEntry:
    """A registered seed function with metadata."""

    def __init__(self, module: str, fn: SeedFn, priority: int, tenant_scoped: bool) -> None:
        self.module = module
        self.fn = fn
        self.priority = priority
        self.tenant_scoped = tenant_scoped


class SeedRunner:
    """Manages and executes seed data functions."""

    def __init__(self) -> None:
        self._seeds: list[_SeedEntry] = []

    def register(
        self,
        module: str,
        *,
        priority: int = 50,
        tenant_scoped: bool = False,
    ) -> Callable:
        """Decorator to register a seed function.

        Args:
            module: The module name this seed belongs to.
            priority: Execution order (lower = earlier). Default 50.
            tenant_scoped: If True, this seed runs per-tenant.
        """

        def decorator(fn: SeedFn) -> SeedFn:
            self._seeds.append(_SeedEntry(module, fn, priority, tenant_scoped))
            self._seeds.sort(key=lambda e: e.priority)
            logger.debug("Registered seed: %s.%s (priority=%d)", module, fn.__name__, priority)
            return fn

        return decorator

    async def run_platform_seeds(self, db: AsyncSession) -> None:
        """Run all platform-level (non-tenant) seeds.

        These create global data: system roles, default permissions,
        platform admin user, etc.
        """
        logger.info("Running platform seeds...")
        for entry in self._seeds:
            if not entry.tenant_scoped:
                try:
                    await entry.fn(db)
                    logger.info("Seed completed: %s.%s", entry.module, entry.fn.__name__)
                except Exception:
                    logger.exception("Seed failed: %s.%s", entry.module, entry.fn.__name__)
                    raise

    async def run_for_tenant(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        """Run all tenant-scoped seeds for a specific tenant.

        These create per-tenant default data: default chart of accounts,
        default product categories, etc.
        """
        logger.info("Running tenant seeds for %s...", tenant_id)
        for entry in self._seeds:
            if entry.tenant_scoped:
                try:
                    await entry.fn(db, tenant_id=tenant_id)
                    logger.info(
                        "Tenant seed completed: %s.%s for %s",
                        entry.module,
                        entry.fn.__name__,
                        tenant_id,
                    )
                except Exception:
                    logger.exception(
                        "Tenant seed failed: %s.%s for %s",
                        entry.module,
                        entry.fn.__name__,
                        tenant_id,
                    )
                    raise

    async def run_all(self, db: AsyncSession) -> None:
        """Run all platform seeds. Tenant seeds must be run separately per tenant."""
        await self.run_platform_seeds(db)


# Singleton
seed_runner = SeedRunner()
