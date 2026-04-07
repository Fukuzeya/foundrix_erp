"""Authentication service: credentials, JWT, tokens, account security, RBAC.

This is the core auth service that handles:
- Password hashing and verification
- JWT access and refresh token management
- Refresh token rotation with reuse detection
- Account lockout after failed login attempts
- User CRUD and tenant role assignment
- System role seeding
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.auth.models import (
    AuditAction,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    SystemRoleType,
    User,
    UserTenantRole,
)
from src.core.auth.password import validate_password_strength
from src.core.config import settings
from src.core.errors.exceptions import ConflictError, NotFoundError, ValidationError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Account lockout configuration
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATIONS_MINUTES = [1, 5, 15, 30, 60]  # Escalating lockout


class AuthService:
    """Production-grade authentication and authorization service."""

    # ── Password hashing ──────────────────────────────────────────────

    def hash_password(self, password: str) -> str:
        """Hash a plaintext password using bcrypt.

        Args:
            password: The plaintext password.

        Returns:
            The bcrypt hash string.
        """
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plaintext password against a bcrypt hash.

        Args:
            plain_password: The plaintext password to check.
            hashed_password: The stored bcrypt hash.

        Returns:
            True if the password matches, False otherwise.
        """
        return pwd_context.verify(plain_password, hashed_password)

    # ── JWT tokens ────────────────────────────────────────────────────

    def create_access_token(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        token_version: int,
    ) -> str:
        """Create a short-lived access token scoped to a user and tenant.

        The token payload includes:
        - ``sub``: user UUID
        - ``tid``: tenant UUID
        - ``type``: ``'access'``
        - ``ver``: token version (must match User.token_version)
        - ``exp``: expiration timestamp

        Args:
            user_id: The authenticated user's UUID.
            tenant_id: The tenant the token is scoped to.
            token_version: The user's current token version.

        Returns:
            An encoded JWT string.
        """
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user_id),
            "tid": str(tenant_id),
            "type": "access",
            "ver": token_version,
            "iat": now,
            "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    async def create_refresh_token(
        self,
        user_id: uuid.UUID,
        db: AsyncSession,
        family_id: uuid.UUID | None = None,
    ) -> str:
        """Create a long-lived refresh token and store its hash in the DB.

        If ``family_id`` is provided, the token belongs to an existing
        rotation chain. Otherwise a new family is created.

        Args:
            user_id: The authenticated user's UUID.
            db: Async session (public schema).
            family_id: Optional family ID for token rotation chains.

        Returns:
            The raw JWT string (only returned once — hash is stored in DB).
        """
        user = await self.get_user_by_id(user_id, db)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        if family_id is None:
            family_id = uuid.uuid4()

        payload = {
            "sub": str(user_id),
            "type": "refresh",
            "fid": str(family_id),
            "ver": user.token_version,
            "iat": now,
            "exp": expires_at,
        }
        raw_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        token_hash = self._hash_token(raw_token)

        refresh_record = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            token_version=user.token_version,
            expires_at=expires_at,
        )
        db.add(refresh_record)
        await db.flush()

        return raw_token

    def decode_token(self, token: str) -> dict:
        """Decode and validate a JWT token.

        Args:
            token: The encoded JWT string.

        Returns:
            The decoded payload dict.

        Raises:
            ValidationError: If the token is expired, malformed, or invalid.
        """
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise ValidationError("Token has expired") from None
        except jwt.InvalidTokenError as exc:
            raise ValidationError(f"Invalid token: {exc}") from None

    async def rotate_refresh_token(
        self,
        raw_token: str,
        db: AsyncSession,
    ) -> tuple[str, uuid.UUID]:
        """Rotate a refresh token: revoke old, issue new in same family.

        Implements refresh token reuse detection: if a revoked token is
        presented, the entire token family is revoked (forces re-login).

        Args:
            raw_token: The raw JWT refresh token string.
            db: Async session (public schema).

        Returns:
            A tuple of (new_raw_token, user_id).

        Raises:
            ValidationError: If the token is invalid, revoked (reuse attack),
                             or the user's token version has changed.
        """
        payload = self.decode_token(raw_token)

        if payload.get("type") != "refresh":
            raise ValidationError("Invalid token type: expected refresh token")

        token_hash = self._hash_token(raw_token)
        user_id = uuid.UUID(payload["sub"])
        family_id = uuid.UUID(payload["fid"])
        token_version = payload.get("ver", 0)

        # Look up the stored token
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        stored_token = result.scalar_one_or_none()

        if stored_token is None:
            raise ValidationError("Refresh token not found")

        # Reuse detection: if this token was already revoked, someone is
        # replaying a stolen token. Revoke the ENTIRE family.
        if stored_token.is_revoked:
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == family_id)
                .values(is_revoked=True)
            )
            await db.flush()
            raise ValidationError(
                "Refresh token reuse detected — all sessions in this family "
                "have been revoked. Please log in again."
            )

        # Verify token version matches the user's current version
        user = await self.get_user_by_id(user_id, db)
        if token_version != user.token_version:
            stored_token.is_revoked = True
            await db.flush()
            raise ValidationError(
                "Token invalidated by password change. Please log in again."
            )

        # Revoke the current token
        stored_token.is_revoked = True
        await db.flush()

        # Issue a new token in the same family
        new_token = await self.create_refresh_token(user_id, db, family_id=family_id)
        return new_token, user_id

    async def revoke_refresh_token(self, raw_token: str, db: AsyncSession) -> None:
        """Revoke a single refresh token (used for logout).

        Args:
            raw_token: The raw JWT refresh token string.
            db: Async session (public schema).
        """
        token_hash = self._hash_token(raw_token)
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .values(is_revoked=True)
        )
        await db.flush()

    async def revoke_all_user_tokens(self, user_id: uuid.UUID, db: AsyncSession) -> None:
        """Revoke all refresh tokens for a user (e.g. after password change).

        Args:
            user_id: The user's UUID.
            db: Async session (public schema).
        """
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked.is_(False),
            )
            .values(is_revoked=True)
        )
        await db.flush()

    async def cleanup_expired_tokens(self, db: AsyncSession) -> int:
        """Delete expired refresh tokens from the database.

        Should be called periodically via a scheduled task.

        Args:
            db: Async session (public schema).

        Returns:
            Number of tokens deleted.
        """
        now = datetime.now(timezone.utc)
        result = await db.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < now)
        )
        await db.flush()
        return result.rowcount

    # ── Account lockout ───────────────────────────────────────────────

    def _get_lockout_duration(self, failed_attempts: int) -> int:
        """Calculate lockout duration in minutes based on failed attempts.

        Uses escalating durations: 1, 5, 15, 30, 60 minutes.

        Args:
            failed_attempts: Number of consecutive failed login attempts.

        Returns:
            Lockout duration in minutes.
        """
        index = min(
            (failed_attempts - MAX_FAILED_ATTEMPTS) // MAX_FAILED_ATTEMPTS,
            len(LOCKOUT_DURATIONS_MINUTES) - 1,
        )
        index = max(0, index)
        return LOCKOUT_DURATIONS_MINUTES[index]

    def _is_account_locked(self, user: User) -> bool:
        """Check if a user account is currently locked.

        Args:
            user: The user to check.

        Returns:
            True if the account is locked, False otherwise.
        """
        if user.locked_until is None:
            return False
        now = datetime.now(timezone.utc)
        if user.locked_until.tzinfo is None:
            locked = user.locked_until.replace(tzinfo=timezone.utc)
        else:
            locked = user.locked_until
        return now < locked

    # ── Authentication ────────────────────────────────────────────────

    async def authenticate(
        self,
        email: str,
        password: str,
        db: AsyncSession,
    ) -> User:
        """Verify user credentials with account lockout protection.

        On success: resets failed attempts and updates last_login_at.
        On failure: increments failed attempts and locks if threshold reached.

        Args:
            email: The user's email address.
            password: The plaintext password.
            db: Async session (public schema).

        Returns:
            The authenticated User instance.

        Raises:
            ValidationError: If credentials are invalid, account is locked,
                             or account is deactivated.
        """
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise ValidationError("Invalid email or password")

        # Check lockout
        if self._is_account_locked(user):
            raise ValidationError(
                "Account is temporarily locked due to too many failed login "
                "attempts. Please try again later."
            )

        if not user.is_active:
            raise ValidationError("User account is deactivated")

        # Verify password
        if not self.verify_password(password, user.hashed_password):
            user.failed_login_attempts += 1

            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                duration = self._get_lockout_duration(user.failed_login_attempts)
                user.locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=duration
                )
            await db.flush()
            raise ValidationError("Invalid email or password")

        # Success: reset lockout state
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(timezone.utc)
        await db.flush()

        return user

    async def change_password(
        self,
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
        db: AsyncSession,
    ) -> User:
        """Change a user's password with validation.

        - Verifies the current password
        - Validates new password strength
        - Hashes and stores the new password
        - Increments token_version to invalidate all existing tokens
        - Revokes all refresh tokens

        Args:
            user_id: The user's UUID.
            current_password: The current plaintext password.
            new_password: The new plaintext password.
            db: Async session (public schema).

        Returns:
            The updated User instance.

        Raises:
            ValidationError: If current password is wrong or new password
                             does not meet policy.
        """
        user = await self.get_user_by_id(user_id, db)

        if not self.verify_password(current_password, user.hashed_password):
            raise ValidationError("Current password is incorrect")

        validate_password_strength(new_password)

        user.hashed_password = self.hash_password(new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        user.token_version += 1
        await db.flush()

        # Revoke all existing refresh tokens
        await self.revoke_all_user_tokens(user_id, db)

        return user

    # ── User operations ───────────────────────────────────────────────

    async def get_user_by_id(self, user_id: uuid.UUID, db: AsyncSession) -> User:
        """Load a user by ID.

        Args:
            user_id: The user's UUID.
            db: Async session (public schema).

        Returns:
            The User instance.

        Raises:
            NotFoundError: If no user with this ID exists.
        """
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundError("User", str(user_id))
        return user

    async def get_user_tenants(
        self,
        user_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[UserTenantRole]:
        """Return all tenant memberships for a user.

        Args:
            user_id: The user's UUID.
            db: Async session (public schema).

        Returns:
            List of UserTenantRole records with tenant and role loaded.
        """
        result = await db.execute(
            select(UserTenantRole)
            .where(
                UserTenantRole.user_id == user_id,
                UserTenantRole.is_active.is_(True),
            )
            .options(
                selectinload(UserTenantRole.tenant),
                selectinload(UserTenantRole.role),
            )
        )
        return list(result.scalars().all())

    async def create_user(
        self,
        email: str,
        password: str,
        full_name: str,
        db: AsyncSession,
    ) -> User:
        """Create a new user account.

        Args:
            email: The user's email address (must be unique).
            password: The plaintext password (validated against policy).
            full_name: The user's display name.
            db: Async session (public schema).

        Returns:
            The newly created User instance.

        Raises:
            ConflictError: If a user with this email already exists.
            ValidationError: If the password does not meet policy.
        """
        validate_password_strength(password)

        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            raise ConflictError(f"User with email '{email}' already exists")

        user = User(
            email=email,
            hashed_password=self.hash_password(password),
            full_name=full_name,
        )
        db.add(user)
        await db.flush()
        return user

    async def assign_tenant_role(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role_id: uuid.UUID,
        db: AsyncSession,
    ) -> UserTenantRole:
        """Assign a user to a tenant with a specific role.

        If the user already has a role in the tenant, it is updated.

        Args:
            user_id: The user's UUID.
            tenant_id: The tenant's UUID.
            role_id: The role's UUID.
            db: Async session (public schema).

        Returns:
            The created or updated UserTenantRole record.
        """
        result = await db.execute(
            select(UserTenantRole).where(
                UserTenantRole.user_id == user_id,
                UserTenantRole.tenant_id == tenant_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.role_id = role_id
            existing.is_active = True
            await db.flush()
            return existing

        user_tenant_role = UserTenantRole(
            user_id=user_id,
            tenant_id=tenant_id,
            role_id=role_id,
        )
        db.add(user_tenant_role)
        await db.flush()
        return user_tenant_role

    async def revoke_tenant_access(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Revoke a user's access to a tenant (soft deactivation).

        Args:
            user_id: The user's UUID.
            tenant_id: The tenant's UUID.
            db: Async session (public schema).
        """
        result = await db.execute(
            select(UserTenantRole).where(
                UserTenantRole.user_id == user_id,
                UserTenantRole.tenant_id == tenant_id,
            )
        )
        utr = result.scalar_one_or_none()
        if utr is not None:
            utr.is_active = False
            await db.flush()

    # ── Role management ───────────────────────────────────────────────

    async def create_role(
        self,
        name: str,
        display_name: str,
        description: str,
        permission_ids: list[uuid.UUID],
        db: AsyncSession,
        tenant_id: uuid.UUID | None = None,
        is_system_role: bool = False,
    ) -> Role:
        """Create a new role with permissions.

        Args:
            name: Machine-readable role name.
            display_name: Human-readable display name.
            description: Role description.
            permission_ids: List of permission UUIDs to assign.
            db: Async session (public schema).
            tenant_id: None for platform roles, set for tenant-specific.
            is_system_role: Whether this is a system-defined role.

        Returns:
            The newly created Role instance.
        """
        existing = await db.execute(
            select(Role).where(
                Role.tenant_id == tenant_id,
                Role.name == name,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError(f"Role '{name}' already exists in this scope")

        role = Role(
            name=name,
            display_name=display_name,
            description=description,
            tenant_id=tenant_id,
            is_system_role=is_system_role,
        )
        db.add(role)
        await db.flush()

        # Assign permissions
        for perm_id in permission_ids:
            role_perm = RolePermission(role_id=role.id, permission_id=perm_id)
            db.add(role_perm)
        await db.flush()

        return role

    async def update_role_permissions(
        self,
        role_id: uuid.UUID,
        permission_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> Role:
        """Replace all permissions on a role.

        System roles cannot have their permissions modified by tenants.

        Args:
            role_id: The role's UUID.
            permission_ids: The new complete list of permission UUIDs.
            db: Async session (public schema).

        Returns:
            The updated Role instance.

        Raises:
            NotFoundError: If the role does not exist.
            ValidationError: If attempting to modify a system role.
        """
        result = await db.execute(
            select(Role).where(Role.id == role_id).options(
                selectinload(Role.role_permissions)
            )
        )
        role = result.scalar_one_or_none()
        if role is None:
            raise NotFoundError("Role", str(role_id))
        if role.is_system_role:
            raise ValidationError("System roles cannot be modified")

        # Delete existing permissions
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )

        # Add new permissions
        for perm_id in permission_ids:
            db.add(RolePermission(role_id=role_id, permission_id=perm_id))
        await db.flush()

        return role

    async def get_roles_for_tenant(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[Role]:
        """Get all roles available to a tenant (platform + tenant-specific).

        Args:
            tenant_id: The tenant's UUID.
            db: Async session (public schema).

        Returns:
            List of Role instances with permissions loaded.
        """
        from sqlalchemy import or_

        result = await db.execute(
            select(Role)
            .where(
                or_(
                    Role.tenant_id == tenant_id,
                    Role.tenant_id.is_(None),
                )
            )
            .options(
                selectinload(Role.role_permissions).selectinload(RolePermission.permission)
            )
        )
        return list(result.scalars().all())

    # ── Permission management ─────────────────────────────────────────

    async def register_permission(
        self,
        codename: str,
        module_name: str,
        description: str,
        db: AsyncSession,
    ) -> Permission:
        """Register a permission (idempotent — skips if already exists).

        Called by the registry during module scanning.

        Args:
            codename: Dotted permission string (e.g. 'contacts.partner.create').
            module_name: The module that owns this permission.
            description: Human-readable description.
            db: Async session (public schema).

        Returns:
            The Permission instance (existing or newly created).
        """
        result = await db.execute(
            select(Permission).where(Permission.codename == codename)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.description = description
            await db.flush()
            return existing

        perm = Permission(
            codename=codename,
            module_name=module_name,
            description=description,
        )
        db.add(perm)
        await db.flush()
        return perm

    async def seed_system_roles(self, db: AsyncSession) -> dict[str, Role]:
        """Seed the default system roles if they don't already exist.

        Called once during application startup. Creates platform-level
        roles with no permissions — permissions are added per-module
        when modules register themselves.

        Args:
            db: Async session (public schema).

        Returns:
            Dict mapping role name to Role instance.
        """
        system_roles = {
            SystemRoleType.PLATFORM_ADMIN: (
                "Platform Administrator",
                "Full access to all tenants and platform settings",
            ),
            SystemRoleType.TENANT_OWNER: (
                "Tenant Owner",
                "Full control over a single tenant including billing and user management",
            ),
            SystemRoleType.TENANT_ADMIN: (
                "Tenant Administrator",
                "Manage users, roles, and modules within a tenant",
            ),
            SystemRoleType.MANAGER: (
                "Manager",
                "Read/write access to business operations",
            ),
            SystemRoleType.MEMBER: (
                "Member",
                "Standard user with basic read/write access",
            ),
            SystemRoleType.VIEWER: (
                "Viewer",
                "Read-only access to permitted modules",
            ),
        }

        created: dict[str, Role] = {}
        for role_type, (display_name, description) in system_roles.items():
            result = await db.execute(
                select(Role).where(
                    Role.name == role_type.value,
                    Role.tenant_id.is_(None),
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                created[role_type.value] = existing
                continue

            role = Role(
                name=role_type.value,
                display_name=display_name,
                description=description,
                tenant_id=None,
                is_system_role=True,
            )
            db.add(role)
            await db.flush()
            created[role_type.value] = role

        return created

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _hash_token(raw_token: str) -> str:
        """SHA-256 hash a raw token for secure storage.

        We never store raw tokens — only hashes. The raw token is
        returned to the client once and verified by hashing on subsequent use.

        Args:
            raw_token: The raw JWT string.

        Returns:
            Hex-encoded SHA-256 hash.
        """
        return hashlib.sha256(raw_token.encode()).hexdigest()


auth_service = AuthService()
