"""Authentication and authorization endpoints.

Public (no auth required):
- POST /auth/login
- POST /auth/refresh

Authenticated:
- GET  /auth/me
- POST /auth/logout
- POST /auth/change-password

Tenant admin:
- GET  /auth/roles
- POST /auth/roles
- PUT  /auth/roles/{role_id}
- POST /auth/roles/assign
- POST /auth/roles/revoke
- GET  /auth/permissions
"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth.audit import extract_client_info, log_audit_event
from src.core.auth.models import AuditAction
from src.core.auth.permissions import (
    get_user_permissions,
    require_permissions,
    require_tenant_role,
)
from src.core.auth.schemas import (
    AssignRoleRequest,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    PermissionRead,
    RefreshRequest,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    TokenResponse,
    UserMeResponse,
    UserRead,
    UserTenantRoleRead,
)
from src.core.auth.service import auth_service
from src.core.config import settings
from src.core.database.session import get_raw_db
from src.core.errors.exceptions import ValidationError

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Public endpoints ──────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
) -> TokenResponse:
    """Authenticate with email and password.

    Returns a tenant-scoped access token and a refresh token.
    Optionally specify ``tenant_id`` to scope to a specific tenant;
    otherwise the user's first active tenant is used.
    """
    ip_address, user_agent = extract_client_info(request)

    try:
        user = await auth_service.authenticate(body.email, body.password, db)
    except ValidationError:
        await log_audit_event(
            db,
            AuditAction.LOGIN_FAILED,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"email": body.email},
        )
        raise

    tenant_roles = await auth_service.get_user_tenants(user.id, db)
    if not tenant_roles:
        raise ValidationError("User is not assigned to any tenant")

    # Determine which tenant to scope the token to
    if body.tenant_id:
        matching = [tr for tr in tenant_roles if tr.tenant_id == body.tenant_id]
        if not matching:
            raise ValidationError("User does not have access to the specified tenant")
        tenant_id = body.tenant_id
    else:
        tenant_id = tenant_roles[0].tenant_id

    access_token = auth_service.create_access_token(
        user.id, tenant_id, user.token_version
    )
    refresh_token = await auth_service.create_refresh_token(user.id, db)

    await log_audit_event(
        db,
        AuditAction.LOGIN_SUCCESS,
        user_id=user.id,
        tenant_id=tenant_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
) -> TokenResponse:
    """Exchange a refresh token for a new token pair.

    Implements token rotation: the old refresh token is revoked and
    a new one is issued. Reuse of a revoked token triggers full
    family revocation (security measure against token theft).
    """
    ip_address, user_agent = extract_client_info(request)

    new_refresh_token, user_id = await auth_service.rotate_refresh_token(
        body.refresh_token, db
    )

    user = await auth_service.get_user_by_id(user_id, db)
    tenant_roles = await auth_service.get_user_tenants(user_id, db)

    if not tenant_roles:
        raise ValidationError("User is not assigned to any tenant")

    # Allow tenant switching on refresh
    if body.tenant_id:
        matching = [tr for tr in tenant_roles if tr.tenant_id == body.tenant_id]
        if not matching:
            raise ValidationError("User does not have access to the specified tenant")
        tenant_id = body.tenant_id
    else:
        tenant_id = tenant_roles[0].tenant_id

    access_token = auth_service.create_access_token(
        user_id, tenant_id, user.token_version
    )

    await log_audit_event(
        db,
        AuditAction.TOKEN_REFRESH,
        user_id=user_id,
        tenant_id=tenant_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Authenticated endpoints ──────────────────────────────────────────


@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
) -> None:
    """Revoke the provided refresh token.

    The access token will naturally expire. For immediate invalidation,
    clients should discard the access token on their side.
    """
    ip_address, user_agent = extract_client_info(request)

    await auth_service.revoke_refresh_token(body.refresh_token, db)

    user = getattr(request.state, "user", None)
    user_id = user.id if user else None

    await log_audit_event(
        db,
        AuditAction.LOGOUT,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.get("/me", response_model=UserMeResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
) -> UserMeResponse:
    """Return the current user's profile, tenant memberships, and permissions.

    Requires a valid access token in the Authorization header.
    """
    current_user = request.state.user
    tenant = getattr(request.state, "tenant", None)

    tenant_roles = await auth_service.get_user_tenants(current_user.id, db)

    tenant_reads = [
        UserTenantRoleRead(
            tenant_id=tr.tenant_id,
            tenant_slug=tr.tenant.slug,
            tenant_name=tr.tenant.name,
            role_id=tr.role_id,
            role_name=tr.role.name,
            is_active=tr.is_active,
        )
        for tr in tenant_roles
    ]

    # Get permissions for the current tenant context
    permissions: list[str] = []
    if tenant:
        permissions = list(
            await get_user_permissions(current_user.id, tenant.id, db)
        )

    return UserMeResponse(
        user=UserRead.model_validate(current_user),
        tenants=tenant_reads,
        permissions=sorted(permissions),
    )


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
) -> None:
    """Change the current user's password.

    Validates the current password, enforces password policy on the
    new password, and invalidates all existing sessions.
    """
    current_user = request.state.user
    ip_address, user_agent = extract_client_info(request)

    await auth_service.change_password(
        current_user.id,
        body.current_password,
        body.new_password,
        db,
    )

    await log_audit_event(
        db,
        AuditAction.PASSWORD_CHANGE,
        user_id=current_user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ── Role management (tenant admin) ───────────────────────────────────


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
    _: None = Depends(require_tenant_role("tenant_owner", "tenant_admin")),
) -> list[RoleRead]:
    """List all roles available to the current tenant.

    Includes both platform-level system roles and custom tenant roles.
    """
    tenant = request.state.tenant
    roles = await auth_service.get_roles_for_tenant(tenant.id, db)

    return [
        RoleRead(
            id=role.id,
            name=role.name,
            display_name=role.display_name,
            description=role.description,
            is_system_role=role.is_system_role,
            tenant_id=role.tenant_id,
            permissions=[
                PermissionRead.model_validate(rp.permission)
                for rp in role.role_permissions
            ],
            created_at=role.created_at,
        )
        for role in roles
    ]


@router.post("/roles", response_model=RoleRead, status_code=201)
async def create_role(
    body: RoleCreate,
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
    _: None = Depends(require_tenant_role("tenant_owner", "tenant_admin")),
) -> RoleRead:
    """Create a custom role for the current tenant."""
    tenant = request.state.tenant

    role = await auth_service.create_role(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        permission_ids=body.permission_ids,
        db=db,
        tenant_id=tenant.id,
    )

    # Reload with permissions
    roles = await auth_service.get_roles_for_tenant(tenant.id, db)
    role = next(r for r in roles if r.id == role.id)

    return RoleRead(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        is_system_role=role.is_system_role,
        tenant_id=role.tenant_id,
        permissions=[
            PermissionRead.model_validate(rp.permission)
            for rp in role.role_permissions
        ],
        created_at=role.created_at,
    )


@router.put("/roles/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
    _: None = Depends(require_tenant_role("tenant_owner", "tenant_admin")),
) -> RoleRead:
    """Update a custom role's display name, description, or permissions.

    System roles cannot be modified.
    """
    if body.permission_ids is not None:
        role = await auth_service.update_role_permissions(
            role_id, body.permission_ids, db
        )
    else:
        from sqlalchemy import select as sa_select
        from src.core.auth.models import Role

        result = await db.execute(sa_select(Role).where(Role.id == role_id))
        role = result.scalar_one_or_none()
        if role is None:
            from src.core.errors.exceptions import NotFoundError
            raise NotFoundError("Role", str(role_id))
        if role.is_system_role:
            raise ValidationError("System roles cannot be modified")

    if body.display_name is not None:
        role.display_name = body.display_name
    if body.description is not None:
        role.description = body.description
    await db.flush()

    tenant = request.state.tenant
    roles = await auth_service.get_roles_for_tenant(tenant.id, db)
    role = next(r for r in roles if r.id == role_id)

    return RoleRead(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        is_system_role=role.is_system_role,
        tenant_id=role.tenant_id,
        permissions=[
            PermissionRead.model_validate(rp.permission)
            for rp in role.role_permissions
        ],
        created_at=role.created_at,
    )


@router.post("/roles/assign", status_code=204)
async def assign_role(
    body: AssignRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
    _: None = Depends(require_tenant_role("tenant_owner", "tenant_admin")),
) -> None:
    """Assign a role to a user within the current tenant."""
    tenant = request.state.tenant
    acting_user = request.state.user
    ip_address, user_agent = extract_client_info(request)

    await auth_service.assign_tenant_role(
        user_id=body.user_id,
        tenant_id=tenant.id,
        role_id=body.role_id,
        db=db,
    )

    await log_audit_event(
        db,
        AuditAction.ROLE_ASSIGNED,
        user_id=acting_user.id,
        tenant_id=tenant.id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "target_user_id": str(body.user_id),
            "role_id": str(body.role_id),
        },
    )


@router.post("/roles/revoke", status_code=204)
async def revoke_role(
    body: AssignRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
    _: None = Depends(require_tenant_role("tenant_owner", "tenant_admin")),
) -> None:
    """Revoke a user's access to the current tenant."""
    tenant = request.state.tenant
    acting_user = request.state.user
    ip_address, user_agent = extract_client_info(request)

    await auth_service.revoke_tenant_access(
        user_id=body.user_id,
        tenant_id=tenant.id,
        db=db,
    )

    await log_audit_event(
        db,
        AuditAction.ROLE_REVOKED,
        user_id=acting_user.id,
        tenant_id=tenant.id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={"target_user_id": str(body.user_id)},
    )


@router.get("/permissions", response_model=list[PermissionRead])
async def list_permissions(
    request: Request,
    db: AsyncSession = Depends(get_raw_db),
    _: None = Depends(require_tenant_role("tenant_owner", "tenant_admin")),
) -> list[PermissionRead]:
    """List all available permissions.

    Used by tenant admins when creating or editing custom roles.
    """
    from sqlalchemy import select as sa_select
    from src.core.auth.models import Permission

    result = await db.execute(sa_select(Permission).order_by(Permission.codename))
    permissions = result.scalars().all()
    return [PermissionRead.model_validate(p) for p in permissions]
