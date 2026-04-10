"""Follow-up repository."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.invoicing.models.followup import FollowUpLevel, PartnerFollowUp


class FollowUpLevelRepository(BaseRepository[FollowUpLevel]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(FollowUpLevel, db)

    async def list_ordered(self) -> list[FollowUpLevel]:
        """List all follow-up levels ordered by delay days."""
        result = await self.db.execute(
            select(FollowUpLevel)
            .where(FollowUpLevel.is_active.is_(True))
            .order_by(FollowUpLevel.delay_days)
        )
        return list(result.scalars().all())

    async def get_level_for_days(self, days_overdue: int) -> FollowUpLevel | None:
        """Get the appropriate follow-up level for a given number of overdue days."""
        result = await self.db.execute(
            select(FollowUpLevel)
            .where(
                FollowUpLevel.is_active.is_(True),
                FollowUpLevel.delay_days <= days_overdue,
            )
            .order_by(FollowUpLevel.delay_days.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class PartnerFollowUpRepository(BaseRepository[PartnerFollowUp]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(PartnerFollowUp, db)

    async def get_by_partner(self, partner_id: uuid.UUID) -> PartnerFollowUp | None:
        result = await self.db.execute(
            select(PartnerFollowUp).where(PartnerFollowUp.partner_id == partner_id)
        )
        return result.scalar_one_or_none()

    async def get_due_followups(self, as_of: date | None = None) -> list[PartnerFollowUp]:
        """Get all partner follow-ups that are due for action."""
        target = as_of or date.today()
        result = await self.db.execute(
            select(PartnerFollowUp)
            .where(
                PartnerFollowUp.blocked.is_(False),
                PartnerFollowUp.next_action_date <= target,
            )
            .order_by(PartnerFollowUp.next_action_date)
        )
        return list(result.scalars().all())

    async def get_or_create(self, partner_id: uuid.UUID) -> PartnerFollowUp:
        """Get or create a follow-up record for a partner."""
        existing = await self.get_by_partner(partner_id)
        if existing:
            return existing
        followup = PartnerFollowUp(partner_id=partner_id)
        self.db.add(followup)
        await self.db.flush()
        await self.db.refresh(followup)
        return followup
