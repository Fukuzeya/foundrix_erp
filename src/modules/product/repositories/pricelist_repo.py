"""Pricelist repositories."""

import uuid
from datetime import datetime

from sqlalchemy import select

from src.core.repository.base import BaseRepository
from src.modules.product.models.pricelist import Pricelist, PricelistItem


class PricelistRepository(BaseRepository[Pricelist]):
    model = Pricelist

    async def find_by_name(self, name: str) -> Pricelist | None:
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Pricelist]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())


class PricelistItemRepository(BaseRepository[PricelistItem]):
    model = PricelistItem

    async def get_applicable_rules(
        self,
        pricelist_id: uuid.UUID,
        now: datetime | None = None,
    ) -> list[PricelistItem]:
        """Get all currently applicable rules for a pricelist, ordered by specificity."""
        query = select(self.model).where(self.model.pricelist_id == pricelist_id)

        if now:
            query = query.where(
                (self.model.date_start.is_(None)) | (self.model.date_start <= now),
                (self.model.date_end.is_(None)) | (self.model.date_end >= now),
            )

        # Order: most specific first (0_variant < 1_product < 2_category < 3_global),
        # then by min_quantity desc, then sequence
        query = query.order_by(
            self.model.applied_on,
            self.model.min_quantity.desc(),
            self.model.sequence,
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def check_pricelist_recursion(self, pricelist_id: uuid.UUID, base_pricelist_id: uuid.UUID) -> bool:
        """DFS check: would setting base_pricelist_id create a cycle?"""
        visited: set[uuid.UUID] = {pricelist_id}
        stack = [base_pricelist_id]

        while stack:
            current = stack.pop()
            if current in visited:
                return True
            visited.add(current)

            # Find all pricelist items that chain to another pricelist
            result = await self.db.execute(
                select(self.model.base_pricelist_id).where(
                    self.model.pricelist_id == current,
                    self.model.base == "pricelist",
                    self.model.base_pricelist_id.isnot(None),
                )
            )
            for row in result.scalars().all():
                stack.append(row)

        return False
