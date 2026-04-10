"""Repositories for InvoiceBatchPayment and BatchPaymentLine."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.repository.base import BaseRepository
from src.modules.invoicing.models.batch_payment import (
    BatchPaymentLine,
    InvoiceBatchPayment,
)


class InvoiceBatchPaymentRepository(BaseRepository[InvoiceBatchPayment]):
    """Repository for invoice batch payments with eager-loaded lines."""

    model = InvoiceBatchPayment

    async def get_with_lines(
        self, batch_id: uuid.UUID,
    ) -> InvoiceBatchPayment | None:
        """Fetch a batch payment with all its lines eagerly loaded."""
        result = await self.db.execute(
            select(self.model)
            .options(selectinload(self.model.lines))
            .where(self.model.id == batch_id)
        )
        return result.scalar_one_or_none()

    async def get_with_lines_or_raise(
        self, batch_id: uuid.UUID,
    ) -> InvoiceBatchPayment:
        """Fetch a batch payment with lines or raise NotFoundError."""
        batch = await self.get_with_lines(batch_id)
        if batch is None:
            from src.core.errors.exceptions import NotFoundError
            raise NotFoundError("InvoiceBatchPayment", str(batch_id))
        return batch

    async def list_by_state(
        self, state: str, *, offset: int = 0, limit: int = 100,
    ) -> list[InvoiceBatchPayment]:
        """List batch payments filtered by state."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.state == state)
            .order_by(self.model.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_journal(
        self, journal_id: uuid.UUID, *, offset: int = 0, limit: int = 100,
    ) -> list[InvoiceBatchPayment]:
        """List batch payments for a specific journal."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.journal_id == journal_id)
            .order_by(self.model.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())


class BatchPaymentLineRepository(BaseRepository[BatchPaymentLine]):
    """Repository for individual batch payment lines."""

    model = BatchPaymentLine

    async def get_by_batch(
        self, batch_id: uuid.UUID,
    ) -> list[BatchPaymentLine]:
        """Fetch all lines belonging to a batch."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.batch_id == batch_id)
            .order_by(self.model.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_by_partner(
        self, partner_id: uuid.UUID,
    ) -> list[BatchPaymentLine]:
        """Fetch all lines for a specific partner across all batches."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.partner_id == partner_id)
            .order_by(self.model.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_pending(
        self, batch_id: uuid.UUID | None = None,
    ) -> list[BatchPaymentLine]:
        """Fetch pending lines, optionally filtered by batch."""
        query = select(self.model).where(self.model.state == "pending")
        if batch_id:
            query = query.where(self.model.batch_id == batch_id)
        query = query.order_by(self.model.created_at.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())
