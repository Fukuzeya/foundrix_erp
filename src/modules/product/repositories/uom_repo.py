"""UoM repositories."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.product.models.uom import Uom, UomCategory


class UomCategoryRepository(BaseRepository[UomCategory]):
    model = UomCategory

    async def find_by_name(self, name: str) -> UomCategory | None:
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()


class UomRepository(BaseRepository[Uom]):
    model = Uom

    async def get_by_category(self, category_id: uuid.UUID) -> list[Uom]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.category_id == category_id, self.model.is_active.is_(True))
            .order_by(self.model.ratio)
        )
        return list(result.scalars().all())

    async def get_reference_uom(self, category_id: uuid.UUID) -> Uom | None:
        result = await self.db.execute(
            select(self.model).where(
                self.model.category_id == category_id,
                self.model.uom_type == "reference",
            )
        )
        return result.scalar_one_or_none()
