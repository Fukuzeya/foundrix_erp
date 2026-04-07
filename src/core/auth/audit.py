"""Audit logging for authentication and authorization events.

Provides a non-blocking function to record security events.
Audit records are append-only and should never be modified or deleted.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth.models import AuditAction, AuditLog

logger = logging.getLogger(__name__)


async def log_audit_event(
    db: AsyncSession,
    action: AuditAction,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an authentication or authorization event.

    This function is designed to never raise — audit failures are logged
    as warnings but do not interrupt the primary operation.

    Args:
        db: Async session (public schema).
        action: The type of event (e.g. LOGIN_SUCCESS, ACCOUNT_LOCKED).
        user_id: The user involved (None if unknown, e.g. bad email login).
        tenant_id: The tenant context (None if not applicable).
        ip_address: Client IP address.
        user_agent: Client User-Agent header.
        details: Additional context as a JSON-serializable dict.
    """
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
        )
        db.add(audit_entry)
        await db.flush()
    except Exception:
        logger.warning(
            "Failed to write audit log: action=%s user=%s",
            action.value,
            user_id,
            exc_info=True,
        )


def extract_client_info(request: Any) -> tuple[str | None, str | None]:
    """Extract IP address and User-Agent from a request.

    Supports both FastAPI/Starlette Request objects. Handles
    X-Forwarded-For for reverse proxy setups.

    Args:
        request: The incoming HTTP request.

    Returns:
        A tuple of (ip_address, user_agent).
    """
    ip_address = None
    user_agent = None

    try:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ip_address = forwarded_for.split(",")[0].strip()
        elif hasattr(request, "client") and request.client:
            ip_address = request.client.host

        user_agent = request.headers.get("User-Agent")
    except Exception:
        logger.warning("Failed to extract client info from request", exc_info=True)

    return ip_address, user_agent
