"""Product tag service — tag management with uniqueness enforcement."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError
from src.modules.product.models.product import ProductTag
from src.modules.product.repositories.product_repo import ProductTagRepository
from src.modules.product.schemas.product import ProductTagCreate

logger = logging.getLogger(__name__)


class ProductTagService:
    """Manages product tags with uniqueness enforcement."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProductTagRepository(db)

    async def list_tags(self) -> list[ProductTag]:
        """List all product tags."""
        return await self.repo.list_all()

    async def create_tag(self, data: ProductTagCreate) -> ProductTag:
        """Create a product tag with name uniqueness check."""
        existing = await self.repo.find_by_name(data.name)
        if existing:
            raise ConflictError(f"Tag '{data.name}' already exists")
        tag = await self.repo.create(**data.model_dump())
        await self.db.flush()
        return tag
