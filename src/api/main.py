"""FastAPI application factory.

Creates and configures the Foundrix ERP application:
1. Sets up structured logging
2. Registers global error handlers
3. Adds tenant resolution, request logging, and CORS middleware
4. Initializes cache and task queue
5. Scans and mounts all ERP modules via the registry
6. Provides system endpoints (/health, /ready, /info)
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.cache import cache
from src.core.config import settings
from src.core.errors.handlers import register_exception_handlers
from src.core.logging import setup_logging
from src.core.logging.middleware import RequestLoggingMiddleware
from src.core.registry.registry import registry
from src.core.tasks import task_queue
from src.core.tenant.middleware import TenantMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown logic."""
    # ── Startup ───────────────────────────────────────────────────
    setup_logging()
    logger.info("Foundrix ERP starting up...")

    # Initialize cache and task queue
    await cache.connect()
    await task_queue.connect()

    # Scan and register modules
    registry.scan_modules("src.modules")
    registry.mount_all_routers(app)
    registry.run_startup_hooks()

    # Seed system roles and module permissions
    await registry.seed_permissions()

    logger.info(
        "Startup complete. %d module(s) loaded: %s",
        len(registry.modules),
        list(registry.modules.keys()),
    )

    yield

    # ── Shutdown ──────────────────────────────────────────────────
    logger.info("Foundrix ERP shutting down...")

    await task_queue.disconnect()
    await cache.disconnect()

    from src.core.database.session import engine

    await engine.dispose()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """Build and return the fully configured FastAPI application."""
    app = FastAPI(
        title="Foundrix ERP",
        description="API-first modular SaaS ERP for African SMEs",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 1. Global error handlers
    register_exception_handlers(app)

    # 2. Request logging (outermost middleware — runs first)
    app.add_middleware(RequestLoggingMiddleware)

    # 3. Tenant resolution middleware
    app.add_middleware(TenantMiddleware)

    # 4. CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:4200",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 5. Core routers (exempt from tenant middleware)
    from src.core.auth.router import router as auth_router
    from src.core.tenant.router import router as tenant_router
    from src.api.system import router as system_router

    app.include_router(auth_router)
    app.include_router(tenant_router)
    app.include_router(system_router)

    return app


app = create_app()
