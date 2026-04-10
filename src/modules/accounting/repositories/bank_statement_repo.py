"""Bank statement repositories."""

import uuid
from sqlalchemy import select
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.bank_statement import BankStatement, BankStatementLine


class BankStatementRepository(BaseRepository[BankStatement]):
    model = BankStatement

    async def get_by_journal(self, journal_id: uuid.UUID) -> list[BankStatement]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.journal_id == journal_id)
            .order_by(self.model.date.desc())
        )
        return list(result.scalars().all())

    async def get_unprocessed(self, journal_id: uuid.UUID | None = None) -> list[BankStatement]:
        query = select(self.model).where(self.model.state == "open")
        if journal_id:
            query = query.where(self.model.journal_id == journal_id)
        result = await self.db.execute(query.order_by(self.model.date))
        return list(result.scalars().all())


class BankStatementLineRepository(BaseRepository[BankStatementLine]):
    model = BankStatementLine

    async def get_by_statement(self, statement_id: uuid.UUID) -> list[BankStatementLine]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.statement_id == statement_id)
            .order_by(self.model.sequence)
        )
        return list(result.scalars().all())

    async def get_unreconciled(self, statement_id: uuid.UUID) -> list[BankStatementLine]:
        result = await self.db.execute(
            select(self.model).where(
                self.model.statement_id == statement_id,
                self.model.is_reconciled.is_(False),
            ).order_by(self.model.sequence)
        )
        return list(result.scalars().all())
