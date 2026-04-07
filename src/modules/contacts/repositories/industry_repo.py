"""Repository for partner industries."""

from sqlalchemy import select

from src.core.repository.base import BaseRepository
from src.modules.contacts.models.partner import PartnerIndustry


class IndustryRepository(BaseRepository[PartnerIndustry]):
    model = PartnerIndustry

    async def find_by_name(self, name: str) -> PartnerIndustry | None:
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[PartnerIndustry]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.name)
        )
        return list(result.scalars().all())
