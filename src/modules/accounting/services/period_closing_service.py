"""Period closing service — fiscal year closing, lock dates, and closing entries.

Handles:
- Pre-closing checks (unposted moves, unreconciled items, draft payments)
- Generating closing journal entries (P&L → retained earnings)
- Setting and querying accounting lock dates
- Closing and reopening fiscal year periods
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
)
from src.core.events import event_bus
from src.modules.accounting.models.account import Account
from src.modules.accounting.models.fiscal_year import FiscalYear
from src.modules.accounting.models.journal import Journal
from src.modules.accounting.models.move import Move, MoveLine

logger = logging.getLogger(__name__)

# Account internal groups that belong to Profit & Loss
_PL_GROUPS = {"income", "expense"}

# The equity account type used for retained earnings
_RETAINED_EARNINGS_TYPE = "equity_unaffected"


class PeriodClosingService:
    """Orchestrates fiscal year period closing operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Closability Checks ─────────────────────────────────────────────

    async def check_period_closable(self, fiscal_year_id: uuid.UUID) -> dict:
        """Check if a fiscal period can be closed.

        Returns a dict with:
        - closable: bool
        - warnings: list of human-readable issues found
        - unposted_moves_count: int
        - unreconciled_items_count: int
        - draft_payments_count: int
        """
        fy = await self._get_fiscal_year(fiscal_year_id)
        warnings: list[str] = []

        # 1. Count unposted (draft) moves within the fiscal year date range
        unposted_moves_count = await self._count_unposted_moves(fy)
        if unposted_moves_count > 0:
            warnings.append(
                f"{unposted_moves_count} unposted journal "
                f"{'entries' if unposted_moves_count != 1 else 'entry'} "
                f"found in the period {fy.date_from} to {fy.date_to}."
            )

        # 2. Count unreconciled items on reconcilable accounts within the period
        unreconciled_items_count = await self._count_unreconciled_items(fy)
        if unreconciled_items_count > 0:
            warnings.append(
                f"{unreconciled_items_count} unreconciled "
                f"{'items' if unreconciled_items_count != 1 else 'item'} "
                f"on receivable/payable accounts."
            )

        # 3. Count draft payments within the period
        draft_payments_count = await self._count_draft_payments(fy)
        if draft_payments_count > 0:
            warnings.append(
                f"{draft_payments_count} draft "
                f"{'payments' if draft_payments_count != 1 else 'payment'} "
                f"found in the period."
            )

        closable = unposted_moves_count == 0

        return {
            "closable": closable,
            "warnings": warnings,
            "unposted_moves_count": unposted_moves_count,
            "unreconciled_items_count": unreconciled_items_count,
            "draft_payments_count": draft_payments_count,
        }

    # ── Close Period ───────────────────────────────────────────────────

    async def close_period(
        self,
        fiscal_year_id: uuid.UUID,
        closing_journal_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict:
        """Close a fiscal year period.

        Steps:
        1. Run closability checks — refuse if hard blockers exist.
        2. Generate closing entries (P&L balances → retained earnings).
        3. Set the fiscal year lock date to the period end date.
        4. Mark the fiscal year as closed.

        Returns a summary dict of the closing operation.
        """
        fy = await self._get_fiscal_year(fiscal_year_id)

        if fy.state == "closed":
            raise ConflictError(
                f"Fiscal year '{fy.name}' is already closed."
            )

        # Validate the closing journal exists and is of type 'general'
        journal = await self._get_journal(closing_journal_id)
        if journal.journal_type != "general":
            raise BusinessRuleError(
                "Closing entries must use a journal of type 'general'."
            )

        # Run closability checks
        check = await self.check_period_closable(fiscal_year_id)
        if not check["closable"]:
            raise BusinessRuleError(
                "Cannot close fiscal year: there are unposted journal entries "
                "in the period. Post or cancel them before closing. "
                + " ".join(check["warnings"])
            )

        # Generate closing journal entry
        closing_move_id = await self.generate_closing_entries(
            fiscal_year_id, closing_journal_id
        )

        # Set the fiscal year lock date to the period end date
        fy.fiscalyear_lock_date = fy.date_to

        # Mark fiscal year as closed
        fy.state = "closed"

        await self.db.flush()

        logger.info(
            "Fiscal year '%s' closed by user %s. Closing entry: %s",
            fy.name,
            user_id,
            closing_move_id,
        )

        await event_bus.publish("fiscal_year.closed", {
            "fiscal_year_id": str(fiscal_year_id),
            "closing_move_id": str(closing_move_id) if closing_move_id else None,
            "user_id": str(user_id),
        })

        return {
            "fiscal_year_id": str(fiscal_year_id),
            "fiscal_year_name": fy.name,
            "state": fy.state,
            "closing_move_id": str(closing_move_id) if closing_move_id else None,
            "lock_date": fy.date_to.isoformat(),
            "warnings": check["warnings"],
        }

    # ── Generate Closing Entries ───────────────────────────────────────

    async def generate_closing_entries(
        self, fiscal_year_id: uuid.UUID, closing_journal_id: uuid.UUID
    ) -> uuid.UUID:
        """Generate a closing journal entry that moves P&L balances to
        retained earnings.

        For each income/expense account with a non-zero balance in the
        period, a line is created to zero it out. The offsetting entry
        goes to the retained earnings (equity_unaffected) account.

        Returns the move_id of the closing entry.
        """
        fy = await self._get_fiscal_year(fiscal_year_id)
        journal = await self._get_journal(closing_journal_id)

        # Find the retained earnings account
        retained_earnings = await self._get_retained_earnings_account()

        # Compute P&L account balances for the fiscal year period
        pl_balances = await self._get_pl_balances(fy)

        if not pl_balances:
            # No P&L activity — still create a zero-line closing entry as a marker
            logger.info(
                "No P&L balances to close for fiscal year '%s'.", fy.name
            )

        # Create the closing move
        closing_move = Move(
            move_type="entry",
            journal_id=journal.id,
            date=fy.date_to,
            ref=f"Closing entry for {fy.name}",
            narration=(
                f"Automatic closing entry generated for fiscal year "
                f"'{fy.name}' ({fy.date_from} to {fy.date_to}). "
                f"Transfers P&L balances to retained earnings."
            ),
            state="draft",
        )
        self.db.add(closing_move)
        await self.db.flush()
        await self.db.refresh(closing_move)

        total_offset_balance = 0.0
        sequence = 10

        for account_id, balance in pl_balances:
            if abs(balance) < 0.01:
                continue

            # To zero out the P&L account, we create the opposite entry:
            # - If balance > 0 (net debit, i.e. expense), credit the account
            # - If balance < 0 (net credit, i.e. income), debit the account
            close_debit = max(-balance, 0.0)
            close_credit = max(balance, 0.0)

            line = MoveLine(
                move_id=closing_move.id,
                account_id=account_id,
                debit=round(close_debit, 2),
                credit=round(close_credit, 2),
                balance=round(close_debit - close_credit, 2),
                amount_currency=round(close_debit - close_credit, 2),
                name=f"Close P&L - {fy.name}",
                display_type="product",
                sequence=sequence,
            )
            self.db.add(line)
            total_offset_balance += balance
            sequence += 10

        # Offsetting line to retained earnings
        # total_offset_balance is the net P&L (positive = net debit/loss)
        # We need to put the total into retained earnings
        if abs(total_offset_balance) >= 0.01:
            offset_debit = max(total_offset_balance, 0.0)
            offset_credit = max(-total_offset_balance, 0.0)

            offset_line = MoveLine(
                move_id=closing_move.id,
                account_id=retained_earnings.id,
                debit=round(offset_debit, 2),
                credit=round(offset_credit, 2),
                balance=round(offset_debit - offset_credit, 2),
                amount_currency=round(offset_debit - offset_credit, 2),
                name=f"Retained earnings - {fy.name}",
                display_type="product",
                sequence=sequence,
            )
            self.db.add(offset_line)

        # Post the closing entry
        closing_move.state = "posted"
        closing_move.name = journal.generate_sequence_name()
        if journal.sequence_next_number is not None:
            journal.sequence_next_number += 1

        await self.db.flush()
        await self.db.refresh(closing_move)

        logger.info(
            "Generated closing entry %s for fiscal year '%s' with %d P&L lines.",
            closing_move.name,
            fy.name,
            len(pl_balances),
        )

        return closing_move.id

    # ── Lock Dates ─────────────────────────────────────────────────────

    async def set_lock_date(
        self, lock_date: date, lock_type: str = "all"
    ) -> None:
        """Set accounting lock date on the fiscal year covering the given date.

        lock_type:
        - 'all': Sets fiscalyear_lock_date (locks all users).
        - 'non_advisers': Sets tax_lock_date (locks non-adviser users).

        The lock date prevents posting or modifying entries on or before
        the specified date.
        """
        if lock_type not in ("all", "non_advisers"):
            raise BusinessRuleError(
                f"Invalid lock_type '{lock_type}'. Must be 'all' or 'non_advisers'."
            )

        fy = await self._get_fiscal_year_for_date(lock_date)

        if fy.hard_lock_date and lock_date < fy.hard_lock_date:
            raise BusinessRuleError(
                f"Cannot set lock date before the hard lock date "
                f"({fy.hard_lock_date.isoformat()}). Hard locks are irreversible."
            )

        if lock_type == "all":
            fy.fiscalyear_lock_date = lock_date
        else:
            fy.tax_lock_date = lock_date

        await self.db.flush()

        logger.info(
            "Lock date set to %s (type=%s) on fiscal year '%s'.",
            lock_date.isoformat(),
            lock_type,
            fy.name,
        )

    async def get_lock_dates(self) -> dict:
        """Return current lock dates configuration across all fiscal years.

        Returns a dict keyed by fiscal year ID with all lock date fields.
        """
        result = await self.db.execute(
            select(FiscalYear).order_by(FiscalYear.date_from.desc())
        )
        fiscal_years = list(result.scalars().all())

        lock_dates: dict = {
            "fiscal_years": [],
            "effective_lock_date": None,
            "effective_tax_lock_date": None,
        }

        latest_lock: date | None = None
        latest_tax_lock: date | None = None

        for fy in fiscal_years:
            entry = {
                "fiscal_year_id": str(fy.id),
                "fiscal_year_name": fy.name,
                "date_from": fy.date_from.isoformat(),
                "date_to": fy.date_to.isoformat(),
                "state": fy.state,
                "sale_lock_date": fy.sale_lock_date.isoformat() if fy.sale_lock_date else None,
                "purchase_lock_date": fy.purchase_lock_date.isoformat() if fy.purchase_lock_date else None,
                "tax_lock_date": fy.tax_lock_date.isoformat() if fy.tax_lock_date else None,
                "fiscalyear_lock_date": fy.fiscalyear_lock_date.isoformat() if fy.fiscalyear_lock_date else None,
                "hard_lock_date": fy.hard_lock_date.isoformat() if fy.hard_lock_date else None,
            }
            lock_dates["fiscal_years"].append(entry)

            # Track the most restrictive lock dates across all fiscal years
            if fy.fiscalyear_lock_date:
                if latest_lock is None or fy.fiscalyear_lock_date > latest_lock:
                    latest_lock = fy.fiscalyear_lock_date
            if fy.tax_lock_date:
                if latest_tax_lock is None or fy.tax_lock_date > latest_tax_lock:
                    latest_tax_lock = fy.tax_lock_date

        lock_dates["effective_lock_date"] = (
            latest_lock.isoformat() if latest_lock else None
        )
        lock_dates["effective_tax_lock_date"] = (
            latest_tax_lock.isoformat() if latest_tax_lock else None
        )

        return lock_dates

    # ── Reopen Period ──────────────────────────────────────────────────

    async def reopen_period(
        self, fiscal_year_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        """Reopen a closed fiscal year.

        Steps:
        1. Validate the fiscal year is currently closed.
        2. Check no hard lock prevents reopening.
        3. Find and reverse the closing journal entry.
        4. Remove the fiscal year lock date.
        5. Set state back to 'open'.
        """
        fy = await self._get_fiscal_year(fiscal_year_id)

        if fy.state != "closed":
            raise BusinessRuleError(
                f"Fiscal year '{fy.name}' is not closed (state: {fy.state})."
            )

        if fy.hard_lock_date and fy.hard_lock_date >= fy.date_to:
            raise BusinessRuleError(
                f"Cannot reopen fiscal year '{fy.name}': a hard lock date "
                f"({fy.hard_lock_date.isoformat()}) prevents modification."
            )

        # Find the closing entry for this fiscal year
        closing_move = await self._find_closing_move(fy)
        if closing_move:
            if closing_move.state == "posted":
                # Create a reversal of the closing entry
                await self._reverse_closing_move(closing_move, fy)
            elif closing_move.state == "draft":
                # Just cancel it
                closing_move.state = "cancel"

        # Remove fiscal year lock date
        fy.fiscalyear_lock_date = None
        fy.state = "open"

        await self.db.flush()

        logger.info(
            "Fiscal year '%s' reopened by user %s.",
            fy.name,
            user_id,
        )

        await event_bus.publish("fiscal_year.reopened", {
            "fiscal_year_id": str(fiscal_year_id),
            "user_id": str(user_id),
        })

    # ── Private Helpers ────────────────────────────────────────────────

    async def _get_fiscal_year(self, fiscal_year_id: uuid.UUID) -> FiscalYear:
        """Fetch a fiscal year by ID or raise NotFoundError."""
        result = await self.db.execute(
            select(FiscalYear).where(FiscalYear.id == fiscal_year_id)
        )
        fy = result.scalar_one_or_none()
        if fy is None:
            raise NotFoundError("FiscalYear", str(fiscal_year_id))
        return fy

    async def _get_fiscal_year_for_date(self, target_date: date) -> FiscalYear:
        """Fetch the fiscal year covering the given date."""
        result = await self.db.execute(
            select(FiscalYear).where(
                FiscalYear.date_from <= target_date,
                FiscalYear.date_to >= target_date,
            )
        )
        fy = result.scalar_one_or_none()
        if fy is None:
            raise NotFoundError("FiscalYear", f"covering date {target_date.isoformat()}")
        return fy

    async def _get_journal(self, journal_id: uuid.UUID) -> Journal:
        """Fetch a journal by ID or raise NotFoundError."""
        result = await self.db.execute(
            select(Journal).where(Journal.id == journal_id)
        )
        journal = result.scalar_one_or_none()
        if journal is None:
            raise NotFoundError("Journal", str(journal_id))
        return journal

    async def _get_retained_earnings_account(self) -> Account:
        """Find the retained earnings (equity_unaffected) account.

        Raises BusinessRuleError if no such account is configured.
        """
        result = await self.db.execute(
            select(Account).where(
                Account.account_type == _RETAINED_EARNINGS_TYPE,
                Account.is_active.is_(True),
            ).limit(1)
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise BusinessRuleError(
                "No retained earnings account found. Please configure an "
                f"account with type '{_RETAINED_EARNINGS_TYPE}' before "
                "closing the fiscal year."
            )
        return account

    async def _count_unposted_moves(self, fy: FiscalYear) -> int:
        """Count draft moves within the fiscal year date range."""
        result = await self.db.execute(
            select(func.count())
            .select_from(Move)
            .where(
                Move.state == "draft",
                Move.date >= fy.date_from,
                Move.date <= fy.date_to,
            )
        )
        return result.scalar() or 0

    async def _count_unreconciled_items(self, fy: FiscalYear) -> int:
        """Count unreconciled move lines on receivable/payable accounts
        for posted moves within the fiscal year period."""
        reconcilable_types = ("asset_receivable", "liability_payable")

        result = await self.db.execute(
            select(func.count())
            .select_from(MoveLine)
            .join(Move, MoveLine.move_id == Move.id)
            .join(Account, MoveLine.account_id == Account.id)
            .where(
                Move.state == "posted",
                Move.date >= fy.date_from,
                Move.date <= fy.date_to,
                Account.account_type.in_(reconcilable_types),
                MoveLine.reconciled.is_(False),
                MoveLine.amount_residual != 0,
            )
        )
        return result.scalar() or 0

    async def _count_draft_payments(self, fy: FiscalYear) -> int:
        """Count draft payment-like moves within the fiscal year period.

        Payments generate moves in bank/cash journals. We identify draft
        payments as draft moves in bank or cash journals.
        """
        result = await self.db.execute(
            select(func.count())
            .select_from(Move)
            .join(Journal, Move.journal_id == Journal.id)
            .where(
                Move.state == "draft",
                Move.date >= fy.date_from,
                Move.date <= fy.date_to,
                Journal.journal_type.in_(("bank", "cash")),
            )
        )
        return result.scalar() or 0

    async def _get_pl_balances(
        self, fy: FiscalYear
    ) -> list[tuple[uuid.UUID, float]]:
        """Get the net balance (sum of debit - credit) for each P&L account
        with posted moves in the fiscal year period.

        Returns a list of (account_id, net_balance) tuples.
        """
        result = await self.db.execute(
            select(
                MoveLine.account_id,
                func.sum(MoveLine.balance).label("net_balance"),
            )
            .join(Move, MoveLine.move_id == Move.id)
            .join(Account, MoveLine.account_id == Account.id)
            .where(
                Move.state == "posted",
                Move.date >= fy.date_from,
                Move.date <= fy.date_to,
                Account.internal_group.in_(_PL_GROUPS),
            )
            .group_by(MoveLine.account_id)
            .having(func.abs(func.sum(MoveLine.balance)) >= 0.01)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def _find_closing_move(self, fy: FiscalYear) -> Move | None:
        """Find the closing journal entry for a fiscal year, identified
        by its ref field and date."""
        result = await self.db.execute(
            select(Move).where(
                Move.ref == f"Closing entry for {fy.name}",
                Move.date == fy.date_to,
                Move.state.in_(("posted", "draft")),
            ).order_by(Move.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def _reverse_closing_move(
        self, closing_move: Move, fy: FiscalYear
    ) -> Move:
        """Create a reversal entry for the closing move."""
        reversal = Move(
            move_type="entry",
            journal_id=closing_move.journal_id,
            date=fy.date_to,
            ref=f"Reversal of closing entry for {fy.name}",
            narration=(
                f"Automatic reversal of closing entry '{closing_move.name}' "
                f"due to fiscal year '{fy.name}' being reopened."
            ),
            reversed_entry_id=closing_move.id,
            state="draft",
        )
        self.db.add(reversal)
        await self.db.flush()

        # Reverse all lines (swap debit/credit)
        for line in closing_move.lines:
            reversed_line = MoveLine(
                move_id=reversal.id,
                account_id=line.account_id,
                partner_id=line.partner_id,
                debit=round(line.credit, 2),
                credit=round(line.debit, 2),
                balance=round(-(line.balance), 2),
                amount_currency=round(-(line.amount_currency), 2),
                currency_code=line.currency_code,
                name=f"Reversal: {line.name or ''}",
                display_type=line.display_type,
                sequence=line.sequence,
            )
            self.db.add(reversed_line)

        # Post the reversal
        journal = await self._get_journal(closing_move.journal_id)
        reversal.state = "posted"
        reversal.name = journal.generate_sequence_name()
        if journal.sequence_next_number is not None:
            journal.sequence_next_number += 1

        await self.db.flush()
        await self.db.refresh(reversal)

        logger.info(
            "Created reversal %s for closing entry %s.",
            reversal.name,
            closing_move.name,
        )

        return reversal
