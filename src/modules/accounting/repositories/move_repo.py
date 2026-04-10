"""Move (Journal Entry) and MoveLine repositories."""

import uuid
from datetime import date

from sqlalchemy import Select, or_, select, func
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.move import Move, MoveLine


class MoveRepository(BaseRepository[Move]):
    model = Move

    def build_filtered_query(
        self,
        *,
        search: str | None = None,
        move_type: str | None = None,
        state: str | None = None,
        journal_id: uuid.UUID | None = None,
        partner_id: uuid.UUID | None = None,
        payment_state: str | None = None,
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
        if move_type:
            query = query.where(self.model.move_type == move_type)
        if state:
            query = query.where(self.model.state == state)
        if journal_id:
            query = query.where(self.model.journal_id == journal_id)
        if partner_id:
            query = query.where(self.model.partner_id == partner_id)
        if payment_state:
            query = query.where(self.model.payment_state == payment_state)
        if date_from:
            query = query.where(self.model.date >= date_from)
        if date_to:
            query = query.where(self.model.date <= date_to)
        return query.order_by(self.model.date.desc(), self.model.name.desc())

    async def get_invoices_by_partner(
        self, partner_id: uuid.UUID, *, state: str | None = "posted"
    ) -> list[Move]:
        query = select(self.model).where(
            self.model.partner_id == partner_id,
            self.model.move_type.in_(["out_invoice", "out_refund", "in_invoice", "in_refund"]),
        )
        if state:
            query = query.where(self.model.state == state)
        result = await self.db.execute(query.order_by(self.model.date.desc()))
        return list(result.scalars().all())

    async def get_unpaid_invoices(self, partner_id: uuid.UUID | None = None) -> list[Move]:
        query = select(self.model).where(
            self.model.state == "posted",
            self.model.payment_state.in_(["not_paid", "partial"]),
            self.model.move_type.in_(["out_invoice", "in_invoice"]),
        )
        if partner_id:
            query = query.where(self.model.partner_id == partner_id)
        result = await self.db.execute(query.order_by(self.model.invoice_date_due))
        return list(result.scalars().all())

    async def get_partner_outstanding(self, partner_id: uuid.UUID) -> float:
        """Sum of amount_residual for posted invoices of a partner."""
        result = await self.db.execute(
            select(func.coalesce(func.sum(self.model.amount_residual), 0))
            .where(
                self.model.partner_id == partner_id,
                self.model.state == "posted",
                self.model.move_type.in_(["out_invoice", "in_invoice"]),
            )
        )
        return result.scalar() or 0.0

    async def get_next_sequence(self, journal_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(self.model)
            .where(self.model.journal_id == journal_id)
        )
        return (result.scalar() or 0) + 1


class MoveLineRepository(BaseRepository[MoveLine]):
    model = MoveLine

    async def get_unreconciled(
        self, account_id: uuid.UUID, partner_id: uuid.UUID | None = None
    ) -> list[MoveLine]:
        query = select(self.model).where(
            self.model.account_id == account_id,
            self.model.reconciled.is_(False),
            self.model.amount_residual != 0,
        )
        if partner_id:
            query = query.where(self.model.partner_id == partner_id)
        result = await self.db.execute(query.order_by(self.model.date_maturity))
        return list(result.scalars().all())

    async def get_by_move(self, move_id: uuid.UUID) -> list[MoveLine]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.move_id == move_id)
            .order_by(self.model.sequence)
        )
        return list(result.scalars().all())

    async def get_balance_by_account(self, account_id: uuid.UUID) -> float:
        result = await self.db.execute(
            select(func.coalesce(func.sum(self.model.balance), 0))
            .where(self.model.account_id == account_id)
        )
        return result.scalar() or 0.0

    async def get_account_balances(self) -> list[dict]:
        """Get sum of debit, credit, balance per account."""
        result = await self.db.execute(
            select(
                self.model.account_id,
                func.sum(self.model.debit).label("total_debit"),
                func.sum(self.model.credit).label("total_credit"),
                func.sum(self.model.balance).label("total_balance"),
            ).group_by(self.model.account_id)
        )
        return [
            {"account_id": r[0], "total_debit": r[1] or 0, "total_credit": r[2] or 0, "total_balance": r[3] or 0}
            for r in result.all()
        ]
