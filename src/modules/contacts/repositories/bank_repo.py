"""Repository for partner bank accounts."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.contacts.models.partner import PartnerBankAccount


class BankAccountRepository(BaseRepository[PartnerBankAccount]):
    model = PartnerBankAccount

    async def get_by_partner(self, partner_id: uuid.UUID) -> list[PartnerBankAccount]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.partner_id == partner_id)
            .order_by(self.model.is_primary.desc())
        )
        return list(result.scalars().all())

    async def find_by_account_number(
        self, partner_id: uuid.UUID, account_number: str
    ) -> PartnerBankAccount | None:
        result = await self.db.execute(
            select(self.model).where(
                self.model.partner_id == partner_id,
                self.model.account_number == account_number,
            )
        )
        return result.scalar_one_or_none()

    async def clear_primary(self, partner_id: uuid.UUID) -> None:
        """Unset is_primary for all bank accounts under a partner."""
        await self.db.execute(
            update(self.model)
            .where(self.model.partner_id == partner_id)
            .values(is_primary=False)
        )
        await self.db.flush()
