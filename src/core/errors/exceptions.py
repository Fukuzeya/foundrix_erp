"""Custom exception hierarchy for the Foundrix ERP platform.

Every exception carries a machine-readable ``code`` and a human-readable
``message`` so that error handlers can produce structured JSON responses.
"""


class FoundrixError(Exception):
    """Base exception for all Foundrix-specific errors."""

    def __init__(self, message: str, code: str = "FOUNDRIX_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class TenantNotFoundError(FoundrixError):
    """Raised when the requested tenant does not exist."""

    def __init__(self, identifier: str) -> None:
        super().__init__(
            message=f"Tenant not found: {identifier}",
            code="TENANT_NOT_FOUND",
        )


class TenantInactiveError(FoundrixError):
    """Raised when the requested tenant exists but is deactivated."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            message=f"Tenant is inactive: {slug}",
            code="TENANT_INACTIVE",
        )


class ModuleNotActiveError(FoundrixError):
    """Raised when a tenant tries to access a module that is not activated."""

    def __init__(self, module_name: str) -> None:
        super().__init__(
            message=f"Module not activated for this tenant: {module_name}",
            code="MODULE_NOT_ACTIVE",
        )


class ValidationError(FoundrixError):
    """Raised when input data fails business-rule validation."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        self.details = details
        super().__init__(message=message, code="VALIDATION_ERROR")


class NotFoundError(FoundrixError):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            message=f"{resource} not found: {identifier}",
            code="NOT_FOUND",
        )


class ConflictError(FoundrixError):
    """Raised when an operation conflicts with existing state (e.g. duplicate)."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="CONFLICT")


class AuthenticationError(FoundrixError):
    """Raised when authentication fails (bad credentials, expired token)."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message=message, code="AUTHENTICATION_ERROR")


class AuthorizationError(FoundrixError):
    """Raised when an authenticated user lacks required permissions."""

    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(message=message, code="AUTHORIZATION_ERROR")


class RateLimitError(FoundrixError):
    """Raised when a client exceeds rate limits."""

    def __init__(self, retry_after: int = 60) -> None:
        self.retry_after = retry_after
        super().__init__(
            message=f"Rate limit exceeded. Retry after {retry_after} seconds.",
            code="RATE_LIMIT_EXCEEDED",
        )


class ServiceUnavailableError(FoundrixError):
    """Raised when an external service or dependency is unavailable."""

    def __init__(self, service: str) -> None:
        super().__init__(
            message=f"Service unavailable: {service}",
            code="SERVICE_UNAVAILABLE",
        )


class BusinessRuleError(FoundrixError):
    """Raised when a business rule is violated.

    Use this for domain-specific validations beyond simple input validation,
    e.g. 'Cannot delete a partner with open invoices'.
    """

    def __init__(self, message: str, details: dict | None = None) -> None:
        self.details = details
        super().__init__(message=message, code="BUSINESS_RULE_VIOLATION")
