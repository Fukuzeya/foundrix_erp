"""Bank statement service — statement management and validation.

Handles:
- Bank statement CRUD with lines
- Balance validation (end balance = start + sum of lines)
- Statement confirmation and processing
- Journal validation (must be bank/cash type)
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError, ValidationError
from src.modules.accounting.models.bank_statement import BankStatement, BankStatementLine
from src.modules.accounting.repositories.bank_statement_repo import (
    BankStatementRepository,
    BankStatementLineRepository,
)
from src.modules.accounting.repositories.journal_repo import JournalRepository
from src.modules.accounting.schemas.bank_statement import (
    BankStatementCreate,
    BankStatementUpdate,
)

logger = logging.getLogger(__name__)


class BankStatementService:
    """Manages bank statements with validation and processing."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = BankStatementRepository(db)
        self.line_repo = BankStatementLineRepository(db)
        self.journal_repo = JournalRepository(db)

    async def list_statements(self, journal_id: uuid.UUID | None = None) -> list[BankStatement]:
        """List bank statements, optionally filtered by journal."""
        if journal_id:
            return await self.repo.get_by_journal(journal_id)
        return await self.repo.list_all()

    async def create_statement(self, data: BankStatementCreate) -> BankStatement:
        """Create a bank statement with lines and validation."""
        # Validate journal exists and is bank/cash type
        journal = await self.journal_repo.get_by_id(data.journal_id)
        if not journal:
            raise NotFoundError("Journal", str(data.journal_id))
        if journal.journal_type not in ("bank", "cash"):
            raise BusinessRuleError("Bank statements must use a bank or cash journal")

        stmt_data = data.model_dump(exclude={"lines"})
        stmt = await self.repo.create(**stmt_data)

        # Compute balance_end from lines
        total_amount = 0.0

        if data.lines:
            for i, line_data in enumerate(data.lines):
                line = BankStatementLine(
                    statement_id=stmt.id,
                    sequence=line_data.sequence or (i + 1),
                    **line_data.model_dump(exclude={"sequence"}),
                )
                self.db.add(line)
                total_amount += line_data.amount

        # Set computed balance
        stmt.balance_end = round(data.balance_start + total_amount, 2)

        await self.db.flush()
        await self.db.refresh(stmt)
        return stmt

    async def get_statement(self, statement_id: uuid.UUID) -> BankStatement:
        """Get a bank statement by ID."""
        return await self.repo.get_by_id_or_raise(statement_id, "BankStatement")

    async def update_statement(self, statement_id: uuid.UUID, data: BankStatementUpdate) -> BankStatement:
        """Update a bank statement."""
        stmt = await self.repo.get_by_id_or_raise(statement_id, "BankStatement")

        if stmt.state != "open":
            raise BusinessRuleError("Can only edit open bank statements")

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(stmt, key, value)

        await self.db.flush()
        await self.db.refresh(stmt)
        return stmt

    async def confirm_statement(self, statement_id: uuid.UUID) -> BankStatement:
        """Confirm a bank statement — validate balances and lock."""
        stmt = await self.repo.get_by_id_or_raise(statement_id, "BankStatement")

        if stmt.state != "open":
            raise BusinessRuleError(f"Cannot confirm statement in state '{stmt.state}'")

        # Validate balance
        if abs(stmt.balance_end - stmt.balance_end_real) > 0.01:
            raise BusinessRuleError(
                f"Computed balance ({stmt.balance_end:.2f}) does not match "
                f"real ending balance ({stmt.balance_end_real:.2f})"
            )

        stmt.state = "confirm"
        await self.db.flush()
        return stmt
