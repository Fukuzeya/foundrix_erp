"""Request logging middleware that emits structured log entries per request."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("foundrix.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request with timing, status, tenant, and user context."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        tenant_slug = getattr(getattr(request.state, "tenant", None), "slug", "-")
        user_email = getattr(getattr(request.state, "user", None), "email", "-")

        logger.info(
            "%s %s -> %s [%.1fms] tenant=%s user=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            tenant_slug,
            user_email,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "tenant_id": tenant_slug,
                "user_id": user_email,
            },
        )

        response.headers["X-Request-ID"] = request_id
        return response
