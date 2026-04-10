"""Pricelist service — pricelist and item management.

Handles:
- Pricelist CRUD
- Pricelist item CRUD with circular reference prevention
- Item management as sub-resources of pricelists
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.modules.product.models.pricelist import Pricelist, PricelistItem as PricelistItemModel
from src.modules.product.repositories.pricelist_repo import (
    PricelistRepository,
    PricelistItemRepository,
)
from src.modules.product.schemas.pricelist import (
    PricelistCreate,
    PricelistUpdate,
    PricelistItemCreate,
    PricelistItemUpdate,
)

logger = logging.getLogger(__name__)


class PricelistService:
    """Manages pricelists and their items."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PricelistRepository(db)
        self.item_repo = PricelistItemRepository(db)

    # ── Pricelists ───────────────────────────────────────────────────

    async def list_pricelists(self) -> list[Pricelist]:
        """List all active pricelists."""
        return await self.repo.list_active()

    async def create_pricelist(self, data: PricelistCreate) -> Pricelist:
        """Create a pricelist with optional items."""
        pricelist = await self.repo.create(
            name=data.name,
            sequence=data.sequence,
            currency_code=data.currency_code,
            description=data.description,
        )

        if data.items:
            for item_data in data.items:
                item = PricelistItemModel(
                    pricelist_id=pricelist.id,
                    **item_data.model_dump(),
                )
                self.db.add(item)

        await self.db.flush()
        await self.db.refresh(pricelist)
        return pricelist

    async def get_pricelist(self, pricelist_id: uuid.UUID) -> Pricelist:
        """Get a pricelist by ID."""
        return await self.repo.get_by_id_or_raise(pricelist_id, "Pricelist")

    async def update_pricelist(self, pricelist_id: uuid.UUID, data: PricelistUpdate) -> Pricelist:
        """Update a pricelist."""
        pricelist = await self.repo.get_by_id_or_raise(pricelist_id, "Pricelist")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(pricelist, key, value)

        await self.db.flush()
        await self.db.refresh(pricelist)
        return pricelist

    async def delete_pricelist(self, pricelist_id: uuid.UUID) -> None:
        """Delete a pricelist."""
        await self.repo.get_by_id_or_raise(pricelist_id, "Pricelist")
        await self.repo.delete(pricelist_id)
        await self.db.flush()

    # ── Pricelist Items ──────────────────────────────────────────────

    async def add_item(self, pricelist_id: uuid.UUID, data: PricelistItemCreate) -> PricelistItemModel:
        """Add an item to a pricelist with circular reference prevention."""
        # Validate pricelist exists
        await self.repo.get_by_id_or_raise(pricelist_id, "Pricelist")

        # Check circular reference for pricelist-based items
        if data.base == "pricelist" and data.base_pricelist_id:
            if await self.item_repo.check_pricelist_recursion(pricelist_id, data.base_pricelist_id):
                raise BusinessRuleError("This would create a circular pricelist reference")

        item = PricelistItemModel(pricelist_id=pricelist_id, **data.model_dump())
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def update_item(self, item_id: uuid.UUID, data: PricelistItemUpdate) -> PricelistItemModel:
        """Update a pricelist item."""
        item = await self.item_repo.get_by_id_or_raise(item_id, "PricelistItem")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(item, key, value)

        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def delete_item(self, item_id: uuid.UUID) -> None:
        """Delete a pricelist item."""
        await self.item_repo.get_by_id_or_raise(item_id, "PricelistItem")
        await self.item_repo.delete(item_id)
        await self.db.flush()
