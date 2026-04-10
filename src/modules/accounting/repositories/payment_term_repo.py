"""Payment term and fiscal position repositories."""

from sqlalchemy import select
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.payment_term import (
    PaymentTerm,
    FiscalPosition,
)


class PaymentTermRepository(BaseRepository[PaymentTerm]):
    model = PaymentTerm

    async def list_active(self) -> list[PaymentTerm]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())

    async def find_by_name(self, name: str) -> PaymentTerm | None:
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()


class FiscalPositionRepository(BaseRepository[FiscalPosition]):
    model = FiscalPosition

    async def list_active(self) -> list[FiscalPosition]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())
