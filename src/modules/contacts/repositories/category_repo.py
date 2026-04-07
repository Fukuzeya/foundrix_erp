"""Repository for partner categories (tags)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.contacts.models.partner import PartnerCategory


class CategoryRepository(BaseRepository[PartnerCategory]):
    model = PartnerCategory

    async def find_by_name(
        self, name: str, parent_id: uuid.UUID | None = None
    ) -> PartnerCategory | None:
        query = select(self.model).where(self.model.name == name)
        if parent_id:
            query = query.where(self.model.parent_id == parent_id)
        else:
            query = query.where(self.model.parent_id.is_(None))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_tree(self) -> list[PartnerCategory]:
        """Get all active categories ordered for tree rendering."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.full_path.asc().nullsfirst(), self.model.name.asc())
        )
        return list(result.scalars().all())

    async def get_children(self, parent_id: uuid.UUID) -> list[PartnerCategory]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.parent_id == parent_id, self.model.is_active.is_(True))
            .order_by(self.model.name)
        )
        return list(result.scalars().all())

    async def has_cycle(self, category_id: uuid.UUID, new_parent_id: uuid.UUID) -> bool:
        """Check if setting new_parent_id would create a cycle."""
        current_id = new_parent_id
        visited: set[uuid.UUID] = set()

        while current_id is not None:
            if current_id == category_id:
                return True
            if current_id in visited:
                return True
            visited.add(current_id)

            result = await self.db.execute(
                select(self.model.parent_id).where(self.model.id == current_id)
            )
            row = result.scalar_one_or_none()
            current_id = row if row else None

        return False
