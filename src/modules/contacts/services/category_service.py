"""Category service — manages hierarchical partner tags."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, ConflictError
from src.modules.contacts.models.partner import PartnerCategory
from src.modules.contacts.repositories.category_repo import CategoryRepository
from src.modules.contacts.schemas.partner import CategoryCreate, CategoryUpdate

logger = logging.getLogger(__name__)


class CategoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CategoryRepository(db)

    async def create_category(self, data: CategoryCreate) -> PartnerCategory:
        """Create a new category with hierarchy validation."""
        # Check duplicate name under same parent
        existing = await self.repo.find_by_name(data.name, data.parent_id)
        if existing:
            raise ConflictError(f"Category '{data.name}' already exists at this level")

        parent = None
        if data.parent_id:
            parent = await self.repo.get_by_id_or_raise(data.parent_id, "Category")

        category = await self.repo.create(**data.model_dump())

        # Compute full_path
        category.full_path = await self._compute_full_path(category, parent)
        await self.db.flush()
        return category

    async def update_category(
        self, category_id: uuid.UUID, data: CategoryUpdate
    ) -> PartnerCategory:
        category = await self.repo.get_by_id_or_raise(category_id, "Category")
        update_data = data.model_dump(exclude_unset=True)

        # Cycle detection on parent change
        new_parent_id = update_data.get("parent_id")
        if new_parent_id is not None and new_parent_id != category.parent_id:
            if await self.repo.has_cycle(category_id, new_parent_id):
                raise BusinessRuleError("This parent assignment would create a cycle")

        for key, value in update_data.items():
            setattr(category, key, value)

        # Recompute full_path
        parent = None
        if category.parent_id:
            parent = await self.repo.get_by_id(category.parent_id)
        category.full_path = await self._compute_full_path(category, parent)

        await self.db.flush()
        await self.db.refresh(category)

        # Update children paths
        await self._recompute_children_paths(category)
        return category

    async def delete_category(self, category_id: uuid.UUID) -> None:
        # Children cascade via FK
        await self.repo.delete(category_id)

    async def list_categories(self) -> list[PartnerCategory]:
        return await self.repo.get_tree()

    async def _compute_full_path(
        self, category: PartnerCategory, parent: PartnerCategory | None
    ) -> str:
        if parent and parent.full_path:
            return f"{parent.full_path} / {category.name}"
        elif parent:
            return f"{parent.name} / {category.name}"
        return category.name

    async def _recompute_children_paths(self, parent: PartnerCategory) -> None:
        children = await self.repo.get_children(parent.id)
        for child in children:
            child.full_path = f"{parent.full_path} / {child.name}" if parent.full_path else child.name
            await self._recompute_children_paths(child)
        if children:
            await self.db.flush()
