"""Generic async repository providing standard CRUD operations.

Modules extend this with domain-specific queries. The repository
encapsulates all SQLAlchemy query logic so that services and routes
never touch the ORM directly.

Usage::

    class PartnerRepository(BaseRepository[Partner]):
        model = Partner

        async def find_by_email(self, email: str) -> Partner | None:
            query = select(self.model).where(self.model.email == email)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.base import Base
from src.core.errors.exceptions import NotFoundError

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Generic async repository with standard CRUD operations.

    Subclasses must set the ``model`` class attribute to the SQLAlchemy
    model class they manage.
    """

    model: type[ModelT]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelT | None:
        """Fetch a single entity by its primary key."""
        result = await self.db.execute(
            select(self.model).where(self.model.id == entity_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(
        self,
        entity_id: uuid.UUID,
        resource_name: str | None = None,
    ) -> ModelT:
        """Fetch by ID or raise NotFoundError."""
        entity = await self.get_by_id(entity_id)
        if entity is None:
            name = resource_name or self.model.__tablename__
            raise NotFoundError(name, str(entity_id))
        return entity

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by: Any | None = None,
        filters: list[Any] | None = None,
    ) -> list[ModelT]:
        """Fetch a list of entities with optional filtering and ordering."""
        query = select(self.model)
        if filters:
            for f in filters:
                query = query.where(f)
        if order_by is not None:
            query = query.order_by(order_by)
        else:
            # Default: order by created_at descending if column exists
            if hasattr(self.model, "created_at"):
                query = query.order_by(self.model.created_at.desc())
        query = query.offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count(self, *, filters: list[Any] | None = None) -> int:
        """Count entities matching optional filters."""
        query = select(func.count()).select_from(self.model)
        if filters:
            for f in filters:
                query = query.where(f)
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def create(self, **kwargs: Any) -> ModelT:
        """Create a new entity and flush to get its ID."""
        entity = self.model(**kwargs)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update(
        self,
        entity_id: uuid.UUID,
        **kwargs: Any,
    ) -> ModelT:
        """Update an existing entity by ID."""
        entity = await self.get_by_id_or_raise(entity_id)
        for key, value in kwargs.items():
            if value is not None:
                setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def delete(self, entity_id: uuid.UUID) -> None:
        """Delete an entity by ID."""
        entity = await self.get_by_id_or_raise(entity_id)
        await self.db.delete(entity)
        await self.db.flush()

    async def bulk_delete(self, *, filters: list[Any]) -> int:
        """Delete multiple entities matching filters. Returns count deleted."""
        query = sa_delete(self.model)
        for f in filters:
            query = query.where(f)
        result = await self.db.execute(query)
        return result.rowcount

    def build_query(self, *, filters: list[Any] | None = None) -> Select:
        """Build a base select query with optional filters.

        Useful for passing to the paginator.
        """
        query = select(self.model)
        if filters:
            for f in filters:
                query = query.where(f)
        return query

    async def exists(self, *, filters: list[Any]) -> bool:
        """Check if any entity matches the given filters."""
        query = select(func.count()).select_from(self.model)
        for f in filters:
            query = query.where(f)
        result = await self.db.execute(query)
        return (result.scalar() or 0) > 0
