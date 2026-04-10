"""Product Category repository."""

import uuid

from sqlalchemy import select

from src.core.repository.base import BaseRepository
from src.modules.product.models.category import ProductCategory


class ProductCategoryRepository(BaseRepository[ProductCategory]):
    model = ProductCategory

    async def find_by_name(self, name: str, parent_id: uuid.UUID | None = None) -> ProductCategory | None:
        query = select(self.model).where(self.model.name == name)
        if parent_id:
            query = query.where(self.model.parent_id == parent_id)
        else:
            query = query.where(self.model.parent_id.is_(None))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_tree(self) -> list[ProductCategory]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.complete_name.asc().nullsfirst(), self.model.name)
        )
        return list(result.scalars().all())

    async def get_ancestors(self, category_id: uuid.UUID) -> list[ProductCategory]:
        """Walk up the tree to collect all ancestors."""
        ancestors: list[ProductCategory] = []
        current_id = category_id

        while current_id is not None:
            cat = await self.get_by_id(current_id)
            if cat is None:
                break
            ancestors.append(cat)
            current_id = cat.parent_id

        return ancestors

    async def is_descendant_of(self, category_id: uuid.UUID, ancestor_id: uuid.UUID) -> bool:
        """Check if category_id is a descendant of ancestor_id."""
        ancestors = await self.get_ancestors(category_id)
        return any(a.id == ancestor_id for a in ancestors)
