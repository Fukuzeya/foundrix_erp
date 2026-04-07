"""Shared FastAPI dependencies injected into module routes.

These dependencies provide:
- The current tenant (resolved by middleware, read from request.state)
- A tenant-scoped database session
- The current authenticated user (decoded from JWT, with token version check)
"""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth.models import User
from src.core.auth.service import auth_service
from src.core.database.session import get_raw_db
from src.core.database.tenant_session import get_tenant_db as _get_tenant_db
from src.core.errors.exceptions import TenantNotFoundError, ValidationError
from src.core.tenant.models import Tenant

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_tenant(request: Request) -> Tenant:
    """Extract the current tenant from request state.

    The ``TenantMiddleware`` resolves the tenant before this runs and
    stores it on ``request.state.tenant``. This dependency simply reads
    it, providing a typed interface for route functions.

    Args:
        request: The incoming HTTP request.

    Returns:
        The resolved Tenant instance.

    Raises:
        TenantNotFoundError: If the middleware did not resolve a tenant
                             (should not happen for non-exempt routes).
    """
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise TenantNotFoundError("No tenant resolved for this request")
    return tenant


async def get_tenant_session(
    tenant: Tenant = Depends(get_current_tenant),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session scoped to the current tenant's schema.

    This is the primary database dependency for all module routes.

    Args:
        tenant: The current tenant (injected).

    Yields:
        An AsyncSession with search_path set to ``tenant_{slug}, public``.
    """
    async for session in _get_tenant_db(tenant.slug):
        yield session


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_raw_db),
) -> User:
    """Decode the JWT access token, verify token version, and return the user.

    Token version checking ensures that tokens issued before a password
    change are rejected — even if they haven't expired yet.

    Also stores the user on ``request.state.user`` so that other
    parts of the system (e.g. auth router, permissions) can access it.

    Args:
        request: The incoming HTTP request.
        token: The Bearer token extracted from the Authorization header.
        db: Public-schema session for user lookup.

    Returns:
        The authenticated User instance.

    Raises:
        ValidationError: If the token is invalid, expired, version mismatched,
                         or the user does not exist / is inactive.
    """
    payload = auth_service.decode_token(token)

    if payload.get("type") != "access":
        raise ValidationError("Invalid token type: expected access token")

    user_id = uuid.UUID(payload["sub"])
    user = await auth_service.get_user_by_id(user_id, db)

    if not user.is_active:
        raise ValidationError("User account is deactivated")

    # Token version check: reject tokens issued before password change
    token_version = payload.get("ver", 0)
    if token_version != user.token_version:
        raise ValidationError(
            "Token invalidated by password change. Please log in again."
        )

    request.state.user = user
    return user
