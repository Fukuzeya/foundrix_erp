"""Product Category service."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, ConflictError
from src.modules.product.models.category import ProductCategory
from src.modules.product.repositories.category_repo import ProductCategoryRepository
from src.modules.product.schemas.category import ProductCategoryCreate, ProductCategoryUpdate

logger = logging.getLogger(__name__)


class ProductCategoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProductCategoryRepository(db)

    async def create_category(self, data: ProductCategoryCreate) -> ProductCategory:
        existing = await self.repo.find_by_name(data.name, data.parent_id)
        if existing:
            raise ConflictError(f"Category '{data.name}' already exists at this level")

        parent = None
        if data.parent_id:
            parent = await self.repo.get_by_id_or_raise(data.parent_id, "ProductCategory")

        category = await self.repo.create(**data.model_dump())

        # Compute complete_name
        if parent and parent.complete_name:
            category.complete_name = f"{parent.complete_name} / {category.name}"
        elif parent:
            category.complete_name = f"{parent.name} / {category.name}"
        else:
            category.complete_name = category.name

        await self.db.flush()
        return category

    async def update_category(
        self, category_id: uuid.UUID, data: ProductCategoryUpdate
    ) -> ProductCategory:
        category = await self.repo.get_by_id_or_raise(category_id, "ProductCategory")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(category, key, value)

        # Recompute complete_name
        parent = None
        if category.parent_id:
            parent = await self.repo.get_by_id(category.parent_id)

        if parent and parent.complete_name:
            category.complete_name = f"{parent.complete_name} / {category.name}"
        elif parent:
            category.complete_name = f"{parent.name} / {category.name}"
        else:
            category.complete_name = category.name

        await self.db.flush()
        await self.db.refresh(category)
        return category

    async def delete_category(self, category_id: uuid.UUID) -> None:
        await self.repo.delete(category_id)

    async def list_categories(self) -> list[ProductCategory]:
        return await self.repo.get_tree()
