"""Permission checking utilities and FastAPI dependency.

Provides functions to verify whether a user has specific permissions
within a tenant, and a dependency factory for use in route definitions.

Usage in module routes::

    from src.core.auth.permissions import require_permissions

    @router.get("/partners")
    async def list_partners(
        user: User = Depends(get_current_user),
        tenant: Tenant = Depends(get_current_tenant),
        db: AsyncSession = Depends(get_raw_db),
        _: None = Depends(require_permissions("contacts.partner.read")),
    ):
        ...
"""

import uuid
from functools import lru_cache

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.auth.models import (
    Permission,
    Role,
    RolePermission,
    User,
    UserTenantRole,
)
from src.core.database.session import get_raw_db
from src.core.errors.exceptions import FoundrixError


class PermissionDeniedError(FoundrixError):
    """Raised when a user lacks the required permission."""

    def __init__(self, permission: str) -> None:
        super().__init__(
            message=f"Permission denied: {permission}",
            code="PERMISSION_DENIED",
        )


async def get_user_permissions(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> set[str]:
    """Fetch all permission codenames for a user within a tenant.

    Resolves the user's role in the tenant, then collects all
    permissions assigned to that role.

    Args:
        user_id: The user's UUID.
        tenant_id: The tenant's UUID.
        db: Async session (public schema).

    Returns:
        A set of permission codename strings.
    """
    result = await db.execute(
        select(UserTenantRole)
        .where(
            UserTenantRole.user_id == user_id,
            UserTenantRole.tenant_id == tenant_id,
            UserTenantRole.is_active.is_(True),
        )
        .options(
            selectinload(UserTenantRole.role)
            .selectinload(Role.role_permissions)
            .selectinload(RolePermission.permission)
        )
    )
    user_tenant_role = result.scalar_one_or_none()

    if user_tenant_role is None:
        return set()

    permissions: set[str] = set()
    for role_perm in user_tenant_role.role.role_permissions:
        permissions.add(role_perm.permission.codename)

    return permissions


async def check_permission(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    permission: str,
    db: AsyncSession,
) -> bool:
    """Check if a user has a specific permission in a tenant.

    Args:
        user_id: The user's UUID.
        tenant_id: The tenant's UUID.
        permission: The permission codename (e.g. 'contacts.partner.create').
        db: Async session (public schema).

    Returns:
        True if the user has the permission, False otherwise.
    """
    user_permissions = await get_user_permissions(user_id, tenant_id, db)
    return permission in user_permissions


async def check_any_permission(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    permissions: list[str],
    db: AsyncSession,
) -> bool:
    """Check if a user has at least one of the listed permissions.

    Args:
        user_id: The user's UUID.
        tenant_id: The tenant's UUID.
        permissions: List of permission codenames to check.
        db: Async session (public schema).

    Returns:
        True if the user has any of the listed permissions.
    """
    user_permissions = await get_user_permissions(user_id, tenant_id, db)
    return bool(user_permissions & set(permissions))


def require_permissions(*required: str):
    """FastAPI dependency factory that enforces permissions on a route.

    Platform admins bypass all permission checks.

    Args:
        *required: One or more permission codenames that are ALL required.

    Returns:
        A FastAPI dependency function.

    Usage::

        @router.post("/partners")
        async def create_partner(
            ...,
            _: None = Depends(require_permissions("contacts.partner.create")),
        ):
            ...
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_raw_db),
    ) -> None:
        user: User = request.state.user
        tenant = getattr(request.state, "tenant", None)

        # Platform admins have all permissions
        if user.is_platform_admin:
            return

        if tenant is None:
            raise PermissionDeniedError(required[0])

        user_permissions = await get_user_permissions(user.id, tenant.id, db)

        for perm in required:
            if perm not in user_permissions:
                raise PermissionDeniedError(perm)

    return _check


def require_any_permission(*required: str):
    """FastAPI dependency factory — requires at least ONE of the permissions.

    Platform admins bypass all checks.

    Args:
        *required: Permission codenames; the user needs at least one.

    Returns:
        A FastAPI dependency function.
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_raw_db),
    ) -> None:
        user: User = request.state.user
        tenant = getattr(request.state, "tenant", None)

        if user.is_platform_admin:
            return

        if tenant is None:
            raise PermissionDeniedError(required[0])

        user_permissions = await get_user_permissions(user.id, tenant.id, db)

        if not (user_permissions & set(required)):
            raise PermissionDeniedError(
                f"Requires one of: {', '.join(required)}"
            )

    return _check


def require_platform_admin():
    """FastAPI dependency that requires the user to be a platform admin.

    Returns:
        A FastAPI dependency function.
    """

    async def _check(request: Request) -> None:
        user: User = request.state.user
        if not user.is_platform_admin:
            raise PermissionDeniedError("platform_admin")

    return _check


def require_tenant_role(*role_names: str):
    """FastAPI dependency factory that requires the user to have a specific
    role (by name) in the current tenant.

    Useful for coarse-grained checks like 'must be tenant_owner or tenant_admin'.

    Args:
        *role_names: Role names that are acceptable.

    Returns:
        A FastAPI dependency function.
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_raw_db),
    ) -> None:
        user: User = request.state.user
        tenant = getattr(request.state, "tenant", None)

        if user.is_platform_admin:
            return

        if tenant is None:
            raise PermissionDeniedError(f"Requires role: {role_names}")

        result = await db.execute(
            select(UserTenantRole)
            .where(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant.id,
                UserTenantRole.is_active.is_(True),
            )
            .options(selectinload(UserTenantRole.role))
        )
        utr = result.scalar_one_or_none()

        if utr is None or utr.role.name not in role_names:
            raise PermissionDeniedError(
                f"Requires role: {', '.join(role_names)}"
            )

    return _check
