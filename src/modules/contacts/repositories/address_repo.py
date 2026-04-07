"""Repository for partner addresses."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.contacts.models.partner import PartnerAddress


class AddressRepository(BaseRepository[PartnerAddress]):
    model = PartnerAddress

    async def get_by_partner(self, partner_id: uuid.UUID) -> list[PartnerAddress]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.partner_id == partner_id)
            .order_by(self.model.is_default.desc(), self.model.address_type)
        )
        return list(result.scalars().all())

    async def get_default_by_type(
        self, partner_id: uuid.UUID, address_type: str
    ) -> PartnerAddress | None:
        result = await self.db.execute(
            select(self.model).where(
                self.model.partner_id == partner_id,
                self.model.address_type == address_type,
                self.model.is_default.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def clear_default_for_type(
        self, partner_id: uuid.UUID, address_type: str
    ) -> None:
        """Unset is_default for all addresses of a given type under a partner."""
        await self.db.execute(
            update(self.model)
            .where(
                self.model.partner_id == partner_id,
                self.model.address_type == address_type,
            )
            .values(is_default=False)
        )
        await self.db.flush()
