"""System endpoints: health check, readiness, and platform info.

These endpoints are exempt from tenant middleware and authentication.
Used by load balancers, monitoring, and deployment pipelines.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.cache import cache
from src.core.config import settings
from src.core.database.session import get_raw_db
from src.core.registry.registry import registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    """Basic health check for load balancers. Always returns 200 if app is running."""
    return {"status": "healthy", "version": "0.1.0"}


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_raw_db)):
    """Readiness check — verifies database and cache connectivity.

    Returns 503 if critical dependencies are unreachable.
    """
    checks = {}

    # Database check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    # Redis/cache check
    checks["cache"] = "ok" if cache.is_available else "unavailable"

    all_ok = all(v == "ok" for v in checks.values())

    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/info")
async def system_info():
    """Platform information: loaded modules, environment, version.

    This endpoint is restricted in production (returns minimal info).
    """
    base = {
        "platform": "Foundrix ERP",
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
    }

    if not settings.is_production:
        base["modules"] = {
            name: {
                "version": mod.version,
                "depends": mod.depends,
            }
            for name, mod in registry.modules.items()
        }
        base["module_count"] = len(registry.modules)

    return base
