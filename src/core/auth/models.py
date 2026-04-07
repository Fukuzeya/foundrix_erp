"""Public schema models for authentication, RBAC, tokens, and audit.

This module defines the complete auth data model:
- User: platform user with security fields (lockout, password tracking)
- Role: custom or system-defined roles per tenant
- Permission: granular module-scoped permissions
- RolePermission: many-to-many role ↔ permission
- UserTenantRole: user ↔ tenant ↔ role assignment
- RefreshToken: stored tokens for rotation and revocation
- AuditLog: immutable log of auth events
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


# ── Enums ─────────────────────────────────────────────────────────────


class SystemRoleType(str, enum.Enum):
    """System-defined role types that are seeded for every tenant."""

    PLATFORM_ADMIN = "platform_admin"
    TENANT_OWNER = "tenant_owner"
    TENANT_ADMIN = "tenant_admin"
    MANAGER = "manager"
    MEMBER = "member"
    VIEWER = "viewer"


class AuditAction(str, enum.Enum):
    """Types of auditable authentication events."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"
    PASSWORD_CHANGE = "password_change"
    PASSWORD_RESET_REQUEST = "password_reset_request"
    PASSWORD_RESET_COMPLETE = "password_reset_complete"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"
    PERMISSION_CHANGED = "permission_changed"
    USER_CREATED = "user_created"
    USER_DEACTIVATED = "user_deactivated"
    USER_REACTIVATED = "user_reactivated"


# ── User ──────────────────────────────────────────────────────────────


class User(UUIDMixin, TimestampMixin, Base):
    """Platform user stored in the public schema.

    Includes security fields for account lockout, password tracking,
    and platform-level admin flag. A user can belong to multiple tenants
    via ``UserTenantRole``.
    """

    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    is_platform_admin: Mapped[bool] = mapped_column(server_default=text("false"))

    # Security fields
    failed_login_attempts: Mapped[int] = mapped_column(server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    password_changed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    token_version: Mapped[int] = mapped_column(
        server_default=text("1"),
        doc="Incremented on password change to invalidate all existing tokens.",
    )

    # Relationships
    tenant_roles: Mapped[list["UserTenantRole"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User email={self.email!r} active={self.is_active}>"


# ── Permission ────────────────────────────────────────────────────────


class Permission(UUIDMixin, Base):
    """A granular permission scoped to a module.

    Permissions follow the pattern ``module.resource.action``, e.g.:
    ``contacts.partner.create``, ``accounting.journal.delete``.

    Modules declare their permissions in ``__manifest__.py`` via
    ``get_permissions()``. The registry seeds them at startup.
    """

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("codename", name="uq_permissions_codename"),
        {"schema": "public"},
    )

    codename: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        doc="Dotted permission string, e.g. 'contacts.partner.create'.",
    )
    module_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="The module that owns this permission.",
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="permission",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Permission {self.codename!r}>"


# ── Role ──────────────────────────────────────────────────────────────


class Role(UUIDMixin, TimestampMixin, Base):
    """A named role that groups permissions.

    Roles can be:
    - **System roles** (``is_system_role=True``): seeded by the platform,
      cannot be deleted or renamed by tenants. Used for default roles like
      Tenant Owner, Admin, Manager, Member, Viewer.
    - **Custom roles** (``is_system_role=False``): created by tenant admins
      for fine-grained access control (e.g. 'Sales Manager', 'Accountant').

    Platform-level roles (``tenant_id=None``) apply across all tenants.
    Tenant-scoped roles (``tenant_id != None``) are specific to one tenant.
    """

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
        {"schema": "public"},
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), server_default=text("''"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="NULL for platform-level roles, set for tenant-specific roles.",
    )
    is_system_role: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="System roles cannot be deleted or renamed by tenants.",
    )

    # Relationships
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    user_tenant_roles: Mapped[list["UserTenantRole"]] = relationship(
        back_populates="role",
    )

    def __repr__(self) -> str:
        scope = f"tenant={self.tenant_id}" if self.tenant_id else "platform"
        return f"<Role {self.name!r} ({scope})>"


# ── RolePermission (M2M) ─────────────────────────────────────────────


class RolePermission(UUIDMixin, Base):
    """Many-to-many link between Role and Permission."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "permission_id", name="uq_role_permissions_role_perm"
        ),
        {"schema": "public"},
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.permissions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Relationships
    role: Mapped["Role"] = relationship(back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship(back_populates="role_permissions")

    def __repr__(self) -> str:
        return f"<RolePermission role={self.role_id} perm={self.permission_id}>"


# ── UserTenantRole ───────────────────────────────────────────────────


class UserTenantRole(UUIDMixin, TimestampMixin, Base):
    """Associates a user with a tenant via a specific role.

    A user may belong to many tenants, each with a different role.
    The unique constraint ensures one role per user per tenant.
    """

    __tablename__ = "user_tenant_roles"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "tenant_id", name="uq_user_tenant_roles_user_tenant"
        ),
        {"schema": "public"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="tenant_roles")
    tenant: Mapped["src.core.tenant.models.Tenant"] = relationship(lazy="selectin")
    role: Mapped["Role"] = relationship(back_populates="user_tenant_roles", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<UserTenantRole user={self.user_id} "
            f"tenant={self.tenant_id} role={self.role_id}>"
        )


# ── RefreshToken ──────────────────────────────────────────────────────


class RefreshToken(UUIDMixin, Base):
    """Stored refresh token for rotation and revocation.

    Each refresh token belongs to a **token family**. When a token is
    used, a new one is issued in the same family and the old one is
    revoked. If a revoked token is reused (replay attack), the entire
    family is revoked — forcing re-authentication.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_token_hash", "token_hash"),
        Index("ix_refresh_tokens_family_id", "family_id"),
        {"schema": "public"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        doc="SHA-256 hash of the raw JWT. Never store the raw token.",
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        doc="Groups tokens in a rotation chain. Reuse of a revoked token "
        "in a family triggers full family revocation.",
    )
    is_revoked: Mapped[bool] = mapped_column(server_default=text("false"))
    token_version: Mapped[int] = mapped_column(
        nullable=False,
        doc="Must match User.token_version to be valid.",
    )
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    def __repr__(self) -> str:
        return f"<RefreshToken user={self.user_id} revoked={self.is_revoked}>"


# ── AuditLog ──────────────────────────────────────────────────────────


class AuditLog(UUIDMixin, Base):
    """Immutable log of authentication and authorization events.

    Used for security monitoring, compliance, and forensics. Records
    are append-only — never updated or deleted.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_created_at", "created_at"),
        {"schema": "public"},
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.users.id", ondelete="SET NULL"),
        nullable=True,
        doc="NULL for events where the user is unknown (e.g. failed login with bad email).",
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action", schema="public"),
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action.value} user={self.user_id}>"
