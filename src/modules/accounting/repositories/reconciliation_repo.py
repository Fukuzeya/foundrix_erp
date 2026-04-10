"""Reconciliation repositories."""

import uuid
from sqlalchemy import select
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.reconciliation import (
    FullReconcile,
    PartialReconcile,
    ReconcileModel,
    ReconcileModelLine,
)


class PartialReconcileRepository(BaseRepository[PartialReconcile]):
    model = PartialReconcile

    async def get_by_debit_line(self, debit_move_line_id: uuid.UUID) -> list[PartialReconcile]:
        result = await self.db.execute(
            select(self.model).where(self.model.debit_move_line_id == debit_move_line_id)
        )
        return list(result.scalars().all())

    async def get_by_credit_line(self, credit_move_line_id: uuid.UUID) -> list[PartialReconcile]:
        result = await self.db.execute(
            select(self.model).where(self.model.credit_move_line_id == credit_move_line_id)
        )
        return list(result.scalars().all())


class FullReconcileRepository(BaseRepository[FullReconcile]):
    model = FullReconcile


class ReconcileModelRepository(BaseRepository[ReconcileModel]):
    model = ReconcileModel

    async def list_active(self) -> list[ReconcileModel]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())
