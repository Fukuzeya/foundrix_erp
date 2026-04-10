"""Incoterm repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.invoicing.models.incoterm import Incoterm


class IncotermRepository(BaseRepository[Incoterm]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Incoterm, db)

    async def find_by_code(self, code: str) -> Incoterm | None:
        result = await self.db.execute(
            select(Incoterm).where(Incoterm.code == code.upper())
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Incoterm]:
        result = await self.db.execute(
            select(Incoterm).where(Incoterm.is_active.is_(True)).order_by(Incoterm.code)
        )
        return list(result.scalars().all())
