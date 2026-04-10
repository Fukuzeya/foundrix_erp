"""Tax repository."""

from sqlalchemy import select
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.tax import Tax, TaxRepartitionLine


class TaxRepository(BaseRepository[Tax]):
    model = Tax

    async def get_by_use(self, type_tax_use: str) -> list[Tax]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.type_tax_use == type_tax_use, self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())

    async def find_by_name(self, name: str, type_tax_use: str) -> Tax | None:
        result = await self.db.execute(
            select(self.model).where(
                self.model.name == name,
                self.model.type_tax_use == type_tax_use,
            )
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Tax]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())


class TaxRepartitionLineRepository(BaseRepository[TaxRepartitionLine]):
    model = TaxRepartitionLine
