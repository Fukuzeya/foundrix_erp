"""Fiscal year and period closing service.

Handles:
- Fiscal year creation and validation
- Period locking (soft/hard)
- Year-end closing entries (P&L → Retained Earnings)
- Lock date enforcement
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.modules.accounting.models.account import Account, BALANCE_SHEET_TYPES
from src.modules.accounting.models.fiscal_year import FiscalYear
from src.modules.accounting.models.move import Move, MoveLine
from src.modules.accounting.repositories.account_repo import AccountRepository
from src.modules.accounting.repositories.fiscal_year_repo import FiscalYearRepository
from src.modules.accounting.repositories.move_repo import MoveLineRepository
from src.modules.accounting.schemas.fiscal_year import FiscalYearCreate

logger = logging.getLogger(__name__)


class FiscalService:
    """Manages fiscal years and period closing."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.fy_repo = FiscalYearRepository(db)
        self.account_repo = AccountRepository(db)
        self.line_repo = MoveLineRepository(db)

    async def list_fiscal_years(self) -> list[FiscalYear]:
        """List all fiscal years ordered by date."""
        return await self.fy_repo.list_all_ordered()

    async def get_fiscal_year(self, fy_id: uuid.UUID) -> FiscalYear:
        """Get a fiscal year by ID."""
        return await self.fy_repo.get_by_id_or_raise(fy_id, "FiscalYear")

    async def create_fiscal_year(self, data: FiscalYearCreate) -> FiscalYear:
        """Create a new fiscal year with validation."""
        # Check for overlapping fiscal years
        existing = await self.fy_repo.list_all_ordered()
        for fy in existing:
            if (data.date_from <= fy.date_to and data.date_to >= fy.date_from):
                raise BusinessRuleError(
                    f"Fiscal year overlaps with '{fy.name}' ({fy.date_from} to {fy.date_to})"
                )

        return await self.fy_repo.create(**data.model_dump())

    async def check_lock_date(self, entry_date: date) -> None:
        """Check if a date is locked for entries."""
        current_fy = await self.fy_repo.get_current(entry_date)
        if not current_fy:
            return

        if current_fy.lock_date and entry_date <= current_fy.lock_date:
            raise BusinessRuleError(
                f"Cannot create/modify entries on or before lock date "
                f"{current_fy.lock_date} (fiscal year: {current_fy.name})"
            )

        if current_fy.tax_lock_date and entry_date <= current_fy.tax_lock_date:
            raise BusinessRuleError(
                f"Tax entries locked on or before {current_fy.tax_lock_date}"
            )

    async def close_fiscal_year(
        self, fiscal_year_id: uuid.UUID, *, retained_earnings_account_id: uuid.UUID,
        closing_journal_id: uuid.UUID,
    ) -> Move:
        """Generate year-end closing entries.

        Transfers P&L balances to retained earnings:
        - All income accounts → Credit to Retained Earnings
        - All expense accounts → Debit from Retained Earnings
        """
        fy = await self.fy_repo.get_by_id_or_raise(fiscal_year_id, "FiscalYear")

        if fy.state == "done":
            raise BusinessRuleError("Fiscal year is already closed")

        retained = await self.account_repo.get_by_id(retained_earnings_account_id)
        if not retained:
            raise NotFoundError("Account", str(retained_earnings_account_id))

        # Get P&L account balances for the fiscal year
        income_accounts = await self.account_repo.get_by_internal_group("income")
        expense_accounts = await self.account_repo.get_by_internal_group("expense")

        from src.modules.accounting.services.move_service import MoveService
        from src.modules.accounting.schemas.move import MoveCreate, MoveLineCreate

        lines: list[MoveLineCreate] = []

        for account in income_accounts + expense_accounts:
            # Get balance for this account within the fiscal year
            balance = await self._get_period_balance(account.id, fy.date_from, fy.date_to)
            if abs(balance) < 0.01:
                continue

            # Close: reverse the balance
            if balance > 0:
                lines.append(MoveLineCreate(
                    account_id=account.id,
                    debit=0.0, credit=balance,
                    name=f"Year-end closing: {account.name}",
                ))
            else:
                lines.append(MoveLineCreate(
                    account_id=account.id,
                    debit=abs(balance), credit=0.0,
                    name=f"Year-end closing: {account.name}",
                ))

        if not lines:
            raise BusinessRuleError("No P&L balances to close")

        # Add retained earnings counterpart
        total_debit = sum(l.debit or 0 for l in lines)
        total_credit = sum(l.credit or 0 for l in lines)
        diff = total_debit - total_credit

        if diff > 0:
            lines.append(MoveLineCreate(
                account_id=retained_earnings_account_id,
                debit=0.0, credit=diff,
                name="Year-end closing: Retained Earnings",
            ))
        elif diff < 0:
            lines.append(MoveLineCreate(
                account_id=retained_earnings_account_id,
                debit=abs(diff), credit=0.0,
                name="Year-end closing: Retained Earnings",
            ))

        move_svc = MoveService(self.db)
        move = await move_svc.create_move(MoveCreate(
            move_type="entry",
            journal_id=closing_journal_id,
            date=fy.date_to,
            ref=f"Year-end closing: {fy.name}",
            lines=lines,
        ))
        await move_svc.post_move(move.id)

        fy.state = "done"
        await self.db.flush()

        return move

    async def _get_period_balance(
        self, account_id: uuid.UUID, date_from: date, date_to: date,
    ) -> float:
        """Get the net balance for an account within a date range."""
        result = await self.db.execute(
            select(func.coalesce(func.sum(MoveLine.balance), 0))
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                MoveLine.account_id == account_id,
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
            )
        )
        return result.scalar() or 0.0
