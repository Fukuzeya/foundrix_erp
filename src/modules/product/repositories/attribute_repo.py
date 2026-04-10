"""Product attribute repositories."""

import uuid

from sqlalchemy import select

from src.core.repository.base import BaseRepository
from src.modules.product.models.attribute import (
    ProductAttribute,
    ProductAttributeValue,
    ProductTemplateAttributeLine,
    ProductTemplateAttributeValue,
)


class ProductAttributeRepository(BaseRepository[ProductAttribute]):
    model = ProductAttribute

    async def find_by_name(self, name: str) -> ProductAttribute | None:
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()


class ProductAttributeValueRepository(BaseRepository[ProductAttributeValue]):
    model = ProductAttributeValue

    async def get_by_attribute(self, attribute_id: uuid.UUID) -> list[ProductAttributeValue]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.attribute_id == attribute_id, self.model.is_active.is_(True))
            .order_by(self.model.sequence)
        )
        return list(result.scalars().all())

    async def get_by_ids(self, ids: list[uuid.UUID]) -> list[ProductAttributeValue]:
        if not ids:
            return []
        result = await self.db.execute(
            select(self.model).where(self.model.id.in_(ids))
        )
        return list(result.scalars().all())


class TemplateAttributeLineRepository(BaseRepository[ProductTemplateAttributeLine]):
    model = ProductTemplateAttributeLine

    async def get_by_template(self, template_id: uuid.UUID) -> list[ProductTemplateAttributeLine]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.product_template_id == template_id)
            .order_by(self.model.sequence)
        )
        return list(result.scalars().all())


class TemplateAttributeValueRepository(BaseRepository[ProductTemplateAttributeValue]):
    model = ProductTemplateAttributeValue

    async def get_by_template(self, template_id: uuid.UUID) -> list[ProductTemplateAttributeValue]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.product_template_id == template_id, self.model.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def get_by_ids(self, ids: list[uuid.UUID]) -> list[ProductTemplateAttributeValue]:
        if not ids:
            return []
        result = await self.db.execute(
            select(self.model).where(self.model.id.in_(ids))
        )
        return list(result.scalars().all())
