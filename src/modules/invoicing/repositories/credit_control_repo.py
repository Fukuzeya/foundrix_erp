"""Credit control repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.invoicing.models.credit_control import CreditControl


class CreditControlRepository(BaseRepository[CreditControl]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(CreditControl, db)

    async def get_by_partner(self, partner_id: uuid.UUID) -> CreditControl | None:
        result = await self.db.execute(
            select(CreditControl).where(CreditControl.partner_id == partner_id)
        )
        return result.scalar_one_or_none()

    async def get_on_hold_partners(self) -> list[CreditControl]:
        """List all partners that are on credit hold."""
        result = await self.db.execute(
            select(CreditControl).where(CreditControl.on_hold.is_(True))
        )
        return list(result.scalars().all())

    async def get_or_create(self, partner_id: uuid.UUID) -> CreditControl:
        """Get or create a credit control record for a partner."""
        existing = await self.get_by_partner(partner_id)
        if existing:
            return existing
        control = CreditControl(partner_id=partner_id)
        self.db.add(control)
        await self.db.flush()
        await self.db.refresh(control)
        return control
