"""Root pytest configuration and shared fixtures.

Provides:
- Async test client (httpx)
- Test database session with automatic rollback
- Factory fixtures for creating test users, tenants, and tokens
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.core.config import settings
from src.core.database.base import Base


# ── Engine and session for tests ─────────────────────────────────────

# Use a separate test database or the same with rollback
TEST_DATABASE_URL = settings.DATABASE_URL

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionFactory = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session that rolls back after each test.

    This ensures tests don't leave persistent state in the database.
    """
    async with test_engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)

        yield session

        await session.close()
        await transaction.rollback()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client.

    The client sends requests to the FastAPI app without starting a server.
    """
    from src.api.main import create_app
    from src.core.database.session import get_raw_db

    app = create_app()

    # Override the DB dependency to use our test session
    async def override_get_raw_db():
        yield db

    app.dependency_overrides[get_raw_db] = override_get_raw_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


# ── Factory fixtures ─────────────────────────────────────────────────


class UserFactory:
    """Helper to create test users."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        email: str | None = None,
        password: str = "TestPass123!",
        full_name: str = "Test User",
        is_platform_admin: bool = False,
    ) -> dict[str, Any]:
        from src.core.auth.service import auth_service

        email = email or f"test_{uuid.uuid4().hex[:8]}@example.com"
        user = await auth_service.create_user(
            email=email,
            password=password,
            full_name=full_name,
            db=self.db,
        )
        if is_platform_admin:
            user.is_platform_admin = True
            await self.db.flush()

        return {
            "user": user,
            "email": email,
            "password": password,
        }


class TenantFactory:
    """Helper to create test tenants."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        slug: str | None = None,
        name: str = "Test Company",
    ) -> Any:
        from src.core.tenant.service import TenantService

        slug = slug or f"test_{uuid.uuid4().hex[:8]}"
        service = TenantService()
        return await service.provision_tenant(slug=slug, name=name, db=self.db)


@pytest_asyncio.fixture
async def user_factory(db: AsyncSession) -> UserFactory:
    return UserFactory(db)


@pytest_asyncio.fixture
async def tenant_factory(db: AsyncSession) -> TenantFactory:
    return TenantFactory(db)
