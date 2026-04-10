"""Deferred Revenue / Expense service — spreads recognition over multiple periods.

When a revenue or expense must be recognised over time (e.g. annual subscription
invoiced upfront, prepaid insurance), this service:

1. Creates a schedule of monthly journal entries that transfer the amount from
   a deferred (balance sheet) account to the P&L account.
2. Processes pending entries up to a given date (typically run monthly).
3. Supports cancellation of remaining unposted entries.

Deferred revenue example (12-month SaaS subscription, $1 200):
  - On invoice: DR Receivable $1 200 / CR Deferred Revenue $1 200
  - Each month: DR Deferred Revenue $100 / CR Revenue $100

Deferred expense example (12-month insurance prepayment, $2 400):
  - On bill: DR Prepaid Expense $2 400 / CR Payable $2 400
  - Each month: DR Insurance Expense $200 / CR Prepaid Expense $200
"""

from __future__ import annotations

import logging
import uuid
from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.accounting.models.account import Account
from src.modules.accounting.models.move import Move, MoveLine
from src.modules.accounting.repositories.account_repo import AccountRepository
from src.modules.accounting.repositories.journal_repo import JournalRepository
from src.modules.accounting.repositories.move_repo import MoveRepository, MoveLineRepository

logger = logging.getLogger(__name__)

# Ref prefix for deferral entries so they can be found and managed
_DEF_REF_PREFIX = "DEFER/"


def _add_months(start: date, months: int) -> date:
    """Return the date that is *months* calendar months after *start*.

    Day is clamped to the last day of the target month (e.g. Jan 31 + 1 month
    = Feb 28).
    """
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


class DeferralService:
    """Creates and manages deferred revenue and deferred expense schedules."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_repo = MoveRepository(db)
        self.line_repo = MoveLineRepository(db)
        self.journal_repo = JournalRepository(db)
        self.account_repo = AccountRepository(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_deferred_revenue(
        self,
        move_line_id: uuid.UUID,
        periods: int,
        start_date: date,
    ) -> list[uuid.UUID]:
        """Create a deferred revenue recognition schedule.

        Given a posted invoice line (e.g. annual subscription), this creates
        ``periods`` draft journal entries, one per month, that transfer
        ``line_amount / periods`` from the deferred revenue account to the
        revenue account.

        Args:
            move_line_id: The invoice product line whose revenue is deferred.
            periods: Number of months over which to recognise revenue.
            start_date: First recognition date (usually first day of service).

        Returns:
            List of created (draft) Move IDs, one per period.
        """
        return await self._create_deferral_schedule(
            move_line_id=move_line_id,
            periods=periods,
            start_date=start_date,
            deferral_type="revenue",
        )

    async def create_deferred_expense(
        self,
        move_line_id: uuid.UUID,
        periods: int,
        start_date: date,
    ) -> list[uuid.UUID]:
        """Create a deferred expense (prepayment) recognition schedule.

        Same as deferred revenue but for expenses: transfers from a prepaid
        expense (asset) account to the expense account each month.

        Args:
            move_line_id: The bill product line whose expense is deferred.
            periods: Number of months over which to recognise the expense.
            start_date: First recognition date.

        Returns:
            List of created (draft) Move IDs.
        """
        return await self._create_deferral_schedule(
            move_line_id=move_line_id,
            periods=periods,
            start_date=start_date,
            deferral_type="expense",
        )

    async def process_deferrals(self, as_of: date) -> dict:
        """Post all pending deferral entries that are due on or before ``as_of``.

        Finds all draft moves whose ``ref`` starts with ``DEFER/`` and whose
        accounting date is <= ``as_of``, then posts them.

        Returns:
            Summary dict with counts and total amounts processed.
        """
        result = await self.db.execute(
            select(Move).where(
                Move.ref.like(f"{_DEF_REF_PREFIX}%"),
                Move.state == "draft",
                Move.date <= as_of,
            ).order_by(Move.date)
        )
        pending_moves = list(result.scalars().all())

        posted_count = 0
        total_amount = 0.0
        posted_ids: list[str] = []
        errors: list[dict] = []

        for move in pending_moves:
            try:
                # Validate the entry balances before posting
                total_debit = sum(l.debit for l in move.lines)
                total_credit = sum(l.credit for l in move.lines)

                if abs(total_debit - total_credit) > 0.01:
                    errors.append({
                        "move_id": str(move.id),
                        "error": f"Unbalanced entry: debits={total_debit:.2f}, credits={total_credit:.2f}",
                    })
                    continue

                # Assign sequence number
                journal = await self.journal_repo.get_by_id(move.journal_id)
                if not journal:
                    errors.append({
                        "move_id": str(move.id),
                        "error": "Journal not found",
                    })
                    continue

                move.name = journal.generate_sequence_name()
                journal.sequence_next_number += 1
                move.state = "posted"

                posted_count += 1
                total_amount += move.amount_total
                posted_ids.append(str(move.id))

            except Exception as exc:
                logger.exception("Failed to post deferral move %s", move.id)
                errors.append({
                    "move_id": str(move.id),
                    "error": str(exc),
                })

        await self.db.flush()

        if posted_ids:
            await event_bus.publish("deferral.processed", {
                "posted_count": posted_count,
                "total_amount": round(total_amount, 2),
                "as_of": as_of.isoformat(),
            })

        return {
            "as_of": as_of.isoformat(),
            "posted_count": posted_count,
            "total_amount": round(total_amount, 2),
            "posted_move_ids": posted_ids,
            "error_count": len(errors),
            "errors": errors,
        }

    async def get_deferral_schedule(
        self, move_line_id: uuid.UUID,
    ) -> list[dict]:
        """Return the full deferral schedule for a source move line.

        Each entry includes the scheduled date, amount, state (draft/posted/cancel),
        and the move reference.
        """
        source_line = await self.line_repo.get_by_id(move_line_id)
        if not source_line:
            raise NotFoundError("MoveLine", str(move_line_id))

        ref_pattern = f"{_DEF_REF_PREFIX}{move_line_id}/%"
        result = await self.db.execute(
            select(Move).where(
                Move.ref.like(ref_pattern),
            ).order_by(Move.date)
        )
        schedule_moves = list(result.scalars().all())

        schedule: list[dict] = []
        for idx, move in enumerate(schedule_moves, start=1):
            # The recognition amount is the move's total
            schedule.append({
                "period": idx,
                "move_id": str(move.id),
                "move_name": move.name,
                "date": move.date.isoformat(),
                "amount": round(move.amount_total, 2),
                "state": move.state,
                "ref": move.ref,
            })

        return schedule

    async def cancel_deferral(self, move_line_id: uuid.UUID) -> None:
        """Cancel all remaining unposted (draft) deferral entries for a source line.

        Posted entries are left untouched; only future scheduled entries are
        cancelled.
        """
        source_line = await self.line_repo.get_by_id(move_line_id)
        if not source_line:
            raise NotFoundError("MoveLine", str(move_line_id))

        ref_pattern = f"{_DEF_REF_PREFIX}{move_line_id}/%"
        result = await self.db.execute(
            select(Move).where(
                Move.ref.like(ref_pattern),
                Move.state == "draft",
            )
        )
        draft_moves = list(result.scalars().all())

        if not draft_moves:
            return

        cancelled_ids: list[str] = []
        for move in draft_moves:
            move.state = "cancel"
            cancelled_ids.append(str(move.id))

        await self.db.flush()

        await event_bus.publish("deferral.cancelled", {
            "move_line_id": str(move_line_id),
            "cancelled_count": len(cancelled_ids),
            "cancelled_move_ids": cancelled_ids,
        })

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _create_deferral_schedule(
        self,
        *,
        move_line_id: uuid.UUID,
        periods: int,
        start_date: date,
        deferral_type: str,  # "revenue" or "expense"
    ) -> list[uuid.UUID]:
        """Core logic shared between deferred revenue and deferred expense."""
        if periods < 1:
            raise BusinessRuleError("Number of periods must be at least 1")

        # Fetch and validate the source move line
        source_line = await self.line_repo.get_by_id(move_line_id)
        if not source_line:
            raise NotFoundError("MoveLine", str(move_line_id))

        source_move = await self.move_repo.get_by_id(source_line.move_id)
        if not source_move:
            raise NotFoundError("Move", str(source_line.move_id))

        if source_move.state != "posted":
            raise BusinessRuleError(
                "Deferral schedules can only be created for posted journal entries"
            )

        if source_line.display_type != "product":
            raise BusinessRuleError(
                "Deferral schedules can only be created for product lines"
            )

        # Check for existing schedule
        existing = await self._has_existing_schedule(move_line_id)
        if existing:
            raise BusinessRuleError(
                f"A deferral schedule already exists for move line {move_line_id}. "
                "Cancel the existing schedule first."
            )

        # Determine the P&L account (from the source line) and deferral account
        pnl_account_id = source_line.account_id
        pnl_account = await self.account_repo.get_by_id(pnl_account_id)
        if not pnl_account:
            raise NotFoundError("Account", str(pnl_account_id))

        deferral_account = await self._find_deferral_account(
            pnl_account, deferral_type,
        )
        if not deferral_account:
            raise BusinessRuleError(
                f"No suitable deferral account found for {deferral_type}. "
                "Please configure a deferred revenue (liability_current) or "
                "prepaid expense (asset_prepayments) account."
            )

        # The total amount to defer is the absolute value of the line's balance
        total_amount = abs(source_line.balance)
        if total_amount < 0.01:
            raise BusinessRuleError("Cannot create deferral for a zero-amount line")

        # Compute per-period amount with rounding correction on the last period
        per_period = round(total_amount / periods, 2)
        amounts = [per_period] * periods
        # Adjust last period for rounding difference
        allocated = per_period * (periods - 1)
        amounts[-1] = round(total_amount - allocated, 2)

        # Use the source move's journal
        journal = await self.journal_repo.get_by_id(source_move.journal_id)
        if not journal:
            raise NotFoundError("Journal", str(source_move.journal_id))

        created_ids: list[uuid.UUID] = []

        for period_idx in range(periods):
            period_date = _add_months(start_date, period_idx)
            amount = amounts[period_idx]

            if amount < 0.01:
                continue

            # Determine debit/credit based on deferral type
            if deferral_type == "revenue":
                # DR Deferred Revenue (liability) / CR Revenue (income)
                debit_account_id = deferral_account.id
                credit_account_id = pnl_account_id
                narration = (
                    f"Deferred revenue recognition period {period_idx + 1}/{periods} "
                    f"for invoice {source_move.name}"
                )
            else:
                # DR Expense (expense) / CR Prepaid Expense (asset)
                debit_account_id = pnl_account_id
                credit_account_id = deferral_account.id
                narration = (
                    f"Deferred expense recognition period {period_idx + 1}/{periods} "
                    f"for bill {source_move.name}"
                )

            move = Move(
                move_type="entry",
                journal_id=journal.id,
                partner_id=source_move.partner_id,
                date=period_date,
                ref=f"{_DEF_REF_PREFIX}{move_line_id}/{period_idx + 1:03d}",
                narration=narration,
                currency_code=source_move.currency_code,
                currency_rate=source_move.currency_rate,
                amount_total=amount,
                state="draft",
            )
            self.db.add(move)
            await self.db.flush()

            debit_line = MoveLine(
                move_id=move.id,
                account_id=debit_account_id,
                partner_id=source_move.partner_id,
                debit=amount,
                credit=0.0,
                balance=amount,
                amount_currency=amount,
                currency_code=source_move.currency_code,
                name=f"Deferral {period_idx + 1}/{periods}: {source_line.name or pnl_account.name}",
                display_type="product",
                quantity=1.0,
                price_unit=amount,
                price_subtotal=amount,
                price_total=amount,
                sequence=10,
            )
            credit_line = MoveLine(
                move_id=move.id,
                account_id=credit_account_id,
                partner_id=source_move.partner_id,
                debit=0.0,
                credit=amount,
                balance=-amount,
                amount_currency=-amount,
                currency_code=source_move.currency_code,
                name=f"Deferral {period_idx + 1}/{periods}: {source_line.name or pnl_account.name}",
                display_type="product",
                quantity=1.0,
                price_unit=amount,
                price_subtotal=amount,
                price_total=amount,
                sequence=20,
            )
            self.db.add(debit_line)
            self.db.add(credit_line)

            await self.db.flush()
            created_ids.append(move.id)

        await event_bus.publish("deferral.schedule_created", {
            "move_line_id": str(move_line_id),
            "deferral_type": deferral_type,
            "periods": periods,
            "total_amount": round(total_amount, 2),
            "move_ids": [str(mid) for mid in created_ids],
        })

        return created_ids

    async def _find_deferral_account(
        self, pnl_account: Account, deferral_type: str,
    ) -> Account | None:
        """Find an appropriate deferral (balance sheet) account.

        For deferred revenue: looks for a ``liability_current`` account with
        'deferred' or 'unearned' in the name. Falls back to any
        ``liability_current`` account.

        For deferred expense: looks for an ``asset_prepayments`` account. Falls
        back to any ``asset_current`` account with 'prepaid' in the name.
        """
        if deferral_type == "revenue":
            target_types = ["liability_current"]
            keywords = ["deferred", "unearned"]
        else:
            target_types = ["asset_prepayments", "asset_current"]
            keywords = ["prepaid", "deferred", "prepayment"]

        # First pass: search by type + keyword in name
        for acct_type in target_types:
            result = await self.db.execute(
                select(Account).where(
                    Account.account_type == acct_type,
                    Account.is_active.is_(True),
                )
            )
            accounts = list(result.scalars().all())

            for kw in keywords:
                for acct in accounts:
                    if kw in acct.name.lower():
                        return acct

            # Second pass: return first account of the target type
            if accounts:
                return accounts[0]

        return None

    async def _has_existing_schedule(self, move_line_id: uuid.UUID) -> bool:
        """Check whether a deferral schedule already exists for this line."""
        ref_pattern = f"{_DEF_REF_PREFIX}{move_line_id}/%"
        result = await self.db.execute(
            select(Move.id).where(
                Move.ref.like(ref_pattern),
                Move.state.in_(["draft", "posted"]),
            ).limit(1)
        )
        return result.scalar() is not None
