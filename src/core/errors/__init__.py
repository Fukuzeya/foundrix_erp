"""Error handling: custom exceptions and global FastAPI handlers."""

from src.core.errors.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BusinessRuleError,
    ConflictError,
    FoundrixError,
    ModuleNotActiveError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    TenantInactiveError,
    TenantNotFoundError,
    ValidationError,
)
from src.core.errors.handlers import register_exception_handlers

__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "BusinessRuleError",
    "ConflictError",
    "FoundrixError",
    "ModuleNotActiveError",
    "NotFoundError",
    "RateLimitError",
    "ServiceUnavailableError",
    "TenantInactiveError",
    "TenantNotFoundError",
    "ValidationError",
    "register_exception_handlers",
]
