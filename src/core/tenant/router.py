"""Tenant management API routes.

These endpoints are for platform admins to manage tenants:
provisioning, activation/deactivation, module management, and
subscription tier changes.
"""

import uuid
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth.models import User
from src.core.auth.permissions import require_platform_admin
from src.core.database.session import get_raw_db
from src.core.errors.exceptions import NotFoundError
from src.core.seed import seed_runner
from src.core.tenant.models import Tenant
from src.core.tenant.schemas import (
    TenantCreate,
    TenantModuleActivate,
    TenantModuleRead,
    TenantRead,
    TenantUpdate,
)
from src.core.tenant.service import TenantService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/tenants", tags=["admin-tenants"])
tenant_service = TenantService()


@router.post("", response_model=TenantRead, status_code=201)
async def create_tenant(
    data: TenantCreate,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """Provision a new tenant with an isolated database schema."""
    tenant = await tenant_service.provision_tenant(
        slug=data.slug,
        name=data.name,
        db=db,
        subscription_tier=data.subscription_tier,
    )
    # Run tenant-scoped seed data
    try:
        await seed_runner.run_for_tenant(db, tenant.id)
    except Exception:
        logger.warning("Tenant seed failed for %s", data.slug, exc_info=True)

    await db.commit()
    return tenant


@router.get("", response_model=list[TenantRead])
async def list_tenants(
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """List all tenants."""
    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{tenant_id}", response_model=TenantRead)
async def get_tenant(
    tenant_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """Get a single tenant by ID."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise NotFoundError("Tenant", str(tenant_id))
    return tenant


@router.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    tenant_id: uuid.UUID,
    data: TenantUpdate,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """Update tenant details (name, subscription tier)."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise NotFoundError("Tenant", str(tenant_id))

    if data.name is not None:
        tenant.name = data.name
    if data.subscription_tier is not None:
        tenant.subscription_tier = data.subscription_tier

    await db.flush()
    await db.commit()
    return tenant


@router.post("/{tenant_id}/deactivate", response_model=TenantRead)
async def deactivate_tenant(
    tenant_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """Deactivate a tenant (soft delete — data is preserved)."""
    tenant = await tenant_service.deactivate_tenant(tenant_id, db)
    await db.commit()
    return tenant


@router.post("/{tenant_id}/activate", response_model=TenantRead)
async def activate_tenant(
    tenant_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """Re-activate a previously deactivated tenant."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise NotFoundError("Tenant", str(tenant_id))
    tenant.is_active = True
    await db.flush()
    await db.commit()
    return tenant


@router.post("/{tenant_id}/modules", response_model=TenantModuleRead, status_code=201)
async def activate_module(
    tenant_id: uuid.UUID,
    data: TenantModuleActivate,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """Activate a module for a tenant."""
    tm = await tenant_service.activate_module(tenant_id, data.module_name, db)
    await db.commit()
    return tm


@router.delete("/{tenant_id}/modules/{module_name}", response_model=TenantModuleRead)
async def deactivate_module(
    tenant_id: uuid.UUID,
    module_name: str,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """Deactivate a module for a tenant."""
    tm = await tenant_service.deactivate_module(tenant_id, module_name, db)
    await db.commit()
    return tm


@router.get("/{tenant_id}/modules", response_model=list[str])
async def list_active_modules(
    tenant_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_raw_db),
):
    """List all active modules for a tenant."""
    return await tenant_service.get_active_modules(tenant_id, db)
