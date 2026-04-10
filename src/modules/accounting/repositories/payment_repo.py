"""Payment and BatchPayment repositories."""

import uuid
from datetime import date

from sqlalchemy import Select, or_, select, func
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.payment import Payment, PaymentMethod, BatchPayment


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    def build_filtered_query(
        self,
        *,
        search: str | None = None,
        payment_type: str | None = None,
        state: str | None = None,
        partner_id: uuid.UUID | None = None,
        journal_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> Select:
        query = select(self.model)
        if search:
            term = f"%{search}%"
            query = query.where(or_(
                self.model.name.ilike(term),
                self.model.ref.ilike(term),
            ))
        if payment_type:
            query = query.where(self.model.payment_type == payment_type)
        if state:
            query = query.where(self.model.state == state)
        if partner_id:
            query = query.where(self.model.partner_id == partner_id)
        if journal_id:
            query = query.where(self.model.journal_id == journal_id)
        if date_from:
            query = query.where(self.model.date >= date_from)
        if date_to:
            query = query.where(self.model.date <= date_to)
        return query.order_by(self.model.date.desc())

    async def get_unposted(self) -> list[Payment]:
        result = await self.db.execute(
            select(self.model).where(self.model.state == "draft")
            .order_by(self.model.date)
        )
        return list(result.scalars().all())


class PaymentMethodRepository(BaseRepository[PaymentMethod]):
    model = PaymentMethod


class BatchPaymentRepository(BaseRepository[BatchPayment]):
    model = BatchPayment
