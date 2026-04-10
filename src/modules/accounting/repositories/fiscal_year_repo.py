"""Fiscal year repository."""

from datetime import date
from sqlalchemy import select
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.fiscal_year import FiscalYear


class FiscalYearRepository(BaseRepository[FiscalYear]):
    model = FiscalYear

    async def get_current(self, as_of: date | None = None) -> FiscalYear | None:
        if as_of is None:
            as_of = date.today()
        result = await self.db.execute(
            select(self.model).where(
                self.model.date_from <= as_of,
                self.model.date_to >= as_of,
            )
        )
        return result.scalar_one_or_none()

    async def list_all_ordered(self) -> list[FiscalYear]:
        result = await self.db.execute(
            select(self.model).order_by(self.model.date_from.desc())
        )
        return list(result.scalars().all())
