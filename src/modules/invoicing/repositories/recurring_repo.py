"""Recurring invoice template repository."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.repository.base import BaseRepository
from src.modules.invoicing.models.recurring import RecurringTemplate, RecurringTemplateLine


class RecurringTemplateRepository(BaseRepository[RecurringTemplate]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(RecurringTemplate, db)

    async def get_with_lines(self, template_id: uuid.UUID) -> RecurringTemplate | None:
        result = await self.db.execute(
            select(RecurringTemplate)
            .options(selectinload(RecurringTemplate.lines))
            .where(RecurringTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[RecurringTemplate]:
        result = await self.db.execute(
            select(RecurringTemplate)
            .options(selectinload(RecurringTemplate.lines))
            .where(RecurringTemplate.is_active.is_(True))
            .order_by(RecurringTemplate.next_invoice_date)
        )
        return list(result.scalars().all())

    async def get_due_templates(self, as_of: date | None = None) -> list[RecurringTemplate]:
        """Get templates that are due for invoice generation."""
        target = as_of or date.today()
        result = await self.db.execute(
            select(RecurringTemplate)
            .options(selectinload(RecurringTemplate.lines))
            .where(
                RecurringTemplate.is_active.is_(True),
                RecurringTemplate.next_invoice_date <= target,
            )
            .order_by(RecurringTemplate.next_invoice_date)
        )
        return list(result.scalars().all())

    async def get_by_partner(self, partner_id: uuid.UUID) -> list[RecurringTemplate]:
        result = await self.db.execute(
            select(RecurringTemplate)
            .options(selectinload(RecurringTemplate.lines))
            .where(RecurringTemplate.partner_id == partner_id)
            .order_by(RecurringTemplate.name)
        )
        return list(result.scalars().all())


class RecurringTemplateLineRepository(BaseRepository[RecurringTemplateLine]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(RecurringTemplateLine, db)

    async def get_by_template(self, template_id: uuid.UUID) -> list[RecurringTemplateLine]:
        result = await self.db.execute(
            select(RecurringTemplateLine)
            .where(RecurringTemplateLine.template_id == template_id)
            .order_by(RecurringTemplateLine.sequence)
        )
        return list(result.scalars().all())
