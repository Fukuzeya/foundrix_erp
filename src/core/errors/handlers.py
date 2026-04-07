"""Global exception handlers registered on the FastAPI application.

Maps each ``FoundrixError`` subclass to the appropriate HTTP status code
and returns a structured JSON error response.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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

logger = logging.getLogger(__name__)

# Maps exception types to HTTP status codes
_STATUS_MAP: dict[type[FoundrixError], int] = {
    TenantNotFoundError: 404,
    TenantInactiveError: 403,
    ModuleNotActiveError: 403,
    ValidationError: 422,
    NotFoundError: 404,
    ConflictError: 409,
    AuthenticationError: 401,
    AuthorizationError: 403,
    RateLimitError: 429,
    ServiceUnavailableError: 503,
    BusinessRuleError: 422,
}


def _build_error_response(exc: FoundrixError, status_code: int) -> JSONResponse:
    """Build a structured JSON error response."""
    headers = {}
    if isinstance(exc, RateLimitError):
        headers["Retry-After"] = str(exc.retry_after)

    body: dict = {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "details": getattr(exc, "details", None),
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers)


async def foundrix_error_handler(request: Request, exc: FoundrixError) -> JSONResponse:
    """Handle all FoundrixError subclasses with structured JSON responses."""
    status_code = _STATUS_MAP.get(type(exc), 500)

    if status_code >= 500:
        logger.error("Unhandled FoundrixError: %s", exc, exc_info=True)
    elif status_code >= 400:
        logger.warning("Client error [%s]: %s", exc.code, exc.message)

    return _build_error_response(exc, status_code)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected exceptions.

    Prevents stack traces from leaking to the client while logging
    the full traceback server-side.
    """
    logger.error("Unhandled exception on %s %s", request.method, request.url, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "details": None,
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the FastAPI application."""
    app.add_exception_handler(FoundrixError, foundrix_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
