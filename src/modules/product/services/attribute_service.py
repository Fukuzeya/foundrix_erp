"""Product attribute service — attribute and value management.

Handles:
- Attribute CRUD with validation
- Attribute value CRUD with parent attribute validation
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError, NotFoundError
from src.modules.product.models.attribute import ProductAttribute, ProductAttributeValue
from src.modules.product.repositories.attribute_repo import (
    ProductAttributeRepository,
    ProductAttributeValueRepository,
)
from src.modules.product.schemas.attribute import (
    ProductAttributeCreate,
    ProductAttributeUpdate,
    ProductAttributeValueCreate,
    ProductAttributeValueUpdate,
)

logger = logging.getLogger(__name__)


class ProductAttributeService:
    """Manages product attributes and their values."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.attr_repo = ProductAttributeRepository(db)
        self.value_repo = ProductAttributeValueRepository(db)

    # ── Attributes ───────────────────────────────────────────────────

    async def list_attributes(self) -> list[ProductAttribute]:
        """List all product attributes."""
        return await self.attr_repo.list_all()

    async def create_attribute(self, data: ProductAttributeCreate) -> ProductAttribute:
        """Create a product attribute."""
        attr = await self.attr_repo.create(**data.model_dump())
        await self.db.flush()
        return attr

    async def get_attribute(self, attribute_id: uuid.UUID) -> ProductAttribute:
        """Get an attribute by ID."""
        return await self.attr_repo.get_by_id_or_raise(attribute_id, "ProductAttribute")

    async def update_attribute(self, attribute_id: uuid.UUID, data: ProductAttributeUpdate) -> ProductAttribute:
        """Update a product attribute."""
        attr = await self.attr_repo.get_by_id_or_raise(attribute_id, "ProductAttribute")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(attr, key, value)

        await self.db.flush()
        await self.db.refresh(attr)
        return attr

    # ── Attribute Values ─────────────────────────────────────────────

    async def list_values(self, attribute_id: uuid.UUID) -> list[ProductAttributeValue]:
        """List all values for a given attribute."""
        # Validate attribute exists
        await self.attr_repo.get_by_id_or_raise(attribute_id, "ProductAttribute")
        return await self.value_repo.get_by_attribute(attribute_id)

    async def create_value(self, data: ProductAttributeValueCreate) -> ProductAttributeValue:
        """Create an attribute value with parent attribute validation."""
        # Validate attribute exists
        await self.attr_repo.get_by_id_or_raise(data.attribute_id, "ProductAttribute")

        value = await self.value_repo.create(**data.model_dump())
        await self.db.flush()
        return value

    async def update_value(self, value_id: uuid.UUID, data: ProductAttributeValueUpdate) -> ProductAttributeValue:
        """Update an attribute value."""
        value = await self.value_repo.get_by_id_or_raise(value_id, "ProductAttributeValue")
        update_data = data.model_dump(exclude_unset=True)

        for key, val in update_data.items():
            setattr(value, key, val)

        await self.db.flush()
        await self.db.refresh(value)
        return value
