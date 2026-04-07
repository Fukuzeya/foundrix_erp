"""Pydantic schemas for authentication, users, roles, and permissions."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ── Auth requests / responses ─────────────────────────────────────────


class LoginRequest(BaseModel):
    """Credentials submitted to the login endpoint."""

    model_config = ConfigDict(strict=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    tenant_id: uuid.UUID | None = Field(
        default=None,
        description="Optional: scope the access token to a specific tenant. "
        "If omitted, the user's first tenant is used.",
    )


class TokenResponse(BaseModel):
    """JWT token pair returned after successful authentication."""

    model_config = ConfigDict(strict=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class RefreshRequest(BaseModel):
    """Payload for the token refresh endpoint."""

    model_config = ConfigDict(strict=True)

    refresh_token: str
    tenant_id: uuid.UUID | None = Field(
        default=None,
        description="Optional: switch tenant context on refresh.",
    )


class LogoutRequest(BaseModel):
    """Payload for the logout endpoint."""

    model_config = ConfigDict(strict=True)

    refresh_token: str


class ChangePasswordRequest(BaseModel):
    """Payload for the password change endpoint."""

    model_config = ConfigDict(strict=True)

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1, max_length=128)


# ── User schemas ──────────────────────────────────────────────────────


class UserCreate(BaseModel):
    """Input schema for creating a new user."""

    model_config = ConfigDict(strict=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class UserRead(BaseModel):
    """Public user profile returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    is_platform_admin: bool
    last_login_at: datetime | None
    created_at: datetime


class UserTenantRoleRead(BaseModel):
    """A single tenant membership with role for the current user."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: uuid.UUID
    tenant_slug: str
    tenant_name: str
    role_id: uuid.UUID
    role_name: str
    is_active: bool


class UserMeResponse(BaseModel):
    """Response for /auth/me — user profile plus tenant memberships."""

    model_config = ConfigDict(from_attributes=True)

    user: UserRead
    tenants: list[UserTenantRoleRead]
    permissions: list[str] = Field(
        description="Permission codenames for the current tenant context"
    )


# ── Role schemas ──────────────────────────────────────────────────────


class PermissionRead(BaseModel):
    """A single permission."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    codename: str
    module_name: str
    description: str


class RoleCreate(BaseModel):
    """Input for creating a custom role."""

    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    permission_ids: list[uuid.UUID] = Field(
        description="List of permission UUIDs to assign to this role"
    )


class RoleRead(BaseModel):
    """A role with its permissions."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_name: str
    description: str
    is_system_role: bool
    tenant_id: uuid.UUID | None
    permissions: list[PermissionRead]
    created_at: datetime


class RoleUpdate(BaseModel):
    """Input for updating a custom role."""

    model_config = ConfigDict(strict=True)

    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    permission_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Replace all permissions with this list",
    )


class AssignRoleRequest(BaseModel):
    """Input for assigning a role to a user in a tenant."""

    model_config = ConfigDict(strict=True)

    user_id: uuid.UUID
    role_id: uuid.UUID
