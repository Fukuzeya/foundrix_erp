"""Base service class for module business logic.

Services orchestrate repositories, enforce business rules, and emit events.
They are the primary unit of business logic and should be the only place
where cross-cutting concerns (events, validation, authorization context)
are combined.

Usage::

    class PartnerService(BaseService[Partner, PartnerRepository]):
        def __init__(self, db: AsyncSession) -> None:
            repo = PartnerRepository(db)
            super().__init__(repo, db)

        async def create_partner(self, data: PartnerCreate) -> Partner:
            partner = await self.repo.create(**data.model_dump())
            await self.emit("partner.created", {"partner_id": str(partner.id)})
            return partner
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.events import event_bus
from src.core.repository.base import BaseRepository

ModelT = TypeVar("ModelT")
RepoT = TypeVar("RepoT", bound=BaseRepository)


class BaseService(Generic[ModelT, RepoT]):
    """Base service providing common patterns for module services."""

    def __init__(self, repo: RepoT, db: AsyncSession) -> None:
        self.repo = repo
        self.db = db

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelT | None:
        """Get entity by ID, returns None if not found."""
        return await self.repo.get_by_id(entity_id)

    async def get_by_id_or_raise(self, entity_id: uuid.UUID) -> ModelT:
        """Get entity by ID or raise NotFoundError."""
        return await self.repo.get_by_id_or_raise(entity_id)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by: Any | None = None,
        filters: list[Any] | None = None,
    ) -> list[ModelT]:
        """List entities with optional filters."""
        return await self.repo.list_all(
            offset=offset, limit=limit, order_by=order_by, filters=filters
        )

    async def delete(self, entity_id: uuid.UUID) -> None:
        """Delete entity by ID."""
        await self.repo.delete(entity_id)

    async def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        """Publish an event through the event bus."""
        await event_bus.publish(event_name, payload)

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.db.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self.db.rollback()
