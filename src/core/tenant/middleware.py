"""Tenant resolution middleware.

Extracts the tenant from every incoming request via header or subdomain,
validates it against the database, and attaches it to ``request.state.tenant``.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.core.database.session import AsyncSessionLocal
from src.core.errors.exceptions import TenantInactiveError, TenantNotFoundError
from src.core.tenant.models import Tenant

# Routes that do not require tenant resolution
EXEMPT_PATHS: set[str] = {
    "/health",
    "/ready",
    "/info",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/login",
    "/auth/refresh",
    "/auth/logout",
    "/auth/me",
    "/auth/change-password",
    "/auth/roles",
    "/auth/permissions",
    "/admin/tenants",
}


def _is_exempt(path: str) -> bool:
    """Return True if the request path is exempt from tenant resolution."""
    return any(path.startswith(exempt) for exempt in EXEMPT_PATHS)


def _extract_slug_from_host(host: str) -> str | None:
    """Extract tenant slug from subdomain (e.g. 'acme.foundrix.app' → 'acme').

    Returns None if no subdomain is present (e.g. 'foundrix.app' or 'localhost').
    """
    parts = host.split(":")[0].split(".")
    if len(parts) > 2:
        return parts[0]
    return None


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware that resolves the current tenant for every request.

    Tenant is identified by either:
    1. ``X-Tenant-ID`` header (slug value) — preferred for API clients
    2. Subdomain extraction (e.g. ``acme.foundrix.app``) — for browser clients
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Resolve tenant and attach to request state, or skip for exempt paths."""
        if _is_exempt(request.url.path):
            return await call_next(request)

        tenant_slug = self._resolve_slug(request)
        if not tenant_slug:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "TENANT_REQUIRED",
                        "message": "Tenant identifier is required. "
                        "Provide X-Tenant-ID header or use a tenant subdomain.",
                    }
                },
            )

        try:
            tenant = await self._load_tenant(tenant_slug)
        except TenantNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": exc.code, "message": exc.message}},
            )
        except TenantInactiveError as exc:
            return JSONResponse(
                status_code=403,
                content={"error": {"code": exc.code, "message": exc.message}},
            )

        request.state.tenant = tenant
        return await call_next(request)

    def _resolve_slug(self, request: Request) -> str | None:
        """Try header first, then subdomain."""
        slug = request.headers.get("X-Tenant-ID")
        if slug:
            return slug.strip().lower()

        host = request.headers.get("host", "")
        return _extract_slug_from_host(host)

    async def _load_tenant(self, slug: str) -> Tenant:
        """Load and validate tenant from the public schema.

        Raises:
            TenantNotFoundError: If no tenant with this slug exists.
            TenantInactiveError: If the tenant exists but is deactivated.
        """
        session: AsyncSession = AsyncSessionLocal()
        try:
            result = await session.execute(
                select(Tenant).where(Tenant.slug == slug)
            )
            tenant = result.scalar_one_or_none()

            if tenant is None:
                raise TenantNotFoundError(slug)
            if not tenant.is_active:
                raise TenantInactiveError(slug)

            return tenant
        finally:
            await session.close()
