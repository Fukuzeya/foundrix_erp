"""Authentication and authorization: models, RBAC, tokens, audit, and permissions."""

from src.core.auth.models import (
    AuditAction,
    AuditLog,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    SystemRoleType,
    User,
    UserTenantRole,
)
from src.core.auth.permissions import (
    PermissionDeniedError,
    check_permission,
    get_user_permissions,
    require_any_permission,
    require_permissions,
    require_platform_admin,
    require_tenant_role,
)
from src.core.auth.service import AuthService, auth_service

__all__ = [
    # Models
    "AuditAction",
    "AuditLog",
    "Permission",
    "RefreshToken",
    "Role",
    "RolePermission",
    "SystemRoleType",
    "User",
    "UserTenantRole",
    # Permissions
    "PermissionDeniedError",
    "check_permission",
    "get_user_permissions",
    "require_any_permission",
    "require_permissions",
    "require_platform_admin",
    "require_tenant_role",
    # Service
    "AuthService",
    "auth_service",
]
