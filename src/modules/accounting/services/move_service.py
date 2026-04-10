"""Journal Entry (Move) service — the core of double-entry accounting.

Handles:
- Creating and validating journal entries
- Invoice creation with automatic tax line generation
- Posting entries (draft → posted) with sequence numbering
- Cancellation and reversal
- Amount computation and balance validation
- Inalterable hash chain for audit compliance
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import (
    BusinessRuleError,
    NotFoundError,
    ValidationError,
)
from src.core.events import event_bus
from src.modules.accounting.models.account import Account, ACCOUNT_TYPE_GROUPS, MUST_RECONCILE_TYPES
from src.modules.accounting.models.move import Move, MoveLine, INVOICE_TYPES
from src.modules.accounting.repositories.account_repo import AccountRepository
from src.modules.accounting.repositories.journal_repo import JournalRepository
from src.modules.accounting.repositories.move_repo import MoveRepository, MoveLineRepository
from src.modules.accounting.schemas.move import MoveCreate, MoveLineCreate, MoveUpdate
from src.modules.accounting.services.tax_service import TaxService

logger = logging.getLogger(__name__)


class MoveService:
    """Orchestrates journal entry and invoice operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_repo = MoveRepository(db)
        self.line_repo = MoveLineRepository(db)
        self.journal_repo = JournalRepository(db)
        self.account_repo = AccountRepository(db)
        self.tax_svc = TaxService(db)

    def build_filtered_query(self, **kwargs):
        """Delegate filtered query construction to the move repository."""
        return self.move_repo.build_filtered_query(**kwargs)

    async def get_move(self, move_id: uuid.UUID) -> Move:
        """Get a move by ID."""
        return await self.move_repo.get_by_id_or_raise(move_id, "Move")

    # ── Create ────────────────────────────────────────────────────────

    async def create_move(self, data: MoveCreate) -> Move:
        """Create a journal entry or invoice in draft state."""
        journal = await self.journal_repo.get_by_id(data.journal_id)
        if not journal:
            raise NotFoundError("Journal", str(data.journal_id))

        move = Move(
            move_type=data.move_type,
            journal_id=data.journal_id,
            partner_id=data.partner_id,
            date=data.date or date.today(),
            invoice_date=data.invoice_date,
            invoice_date_due=data.invoice_date_due,
            currency_code=data.currency_code or journal.currency_code or "USD",
            currency_rate=data.currency_rate or 1.0,
            ref=data.ref,
            narration=data.narration,
            fiscal_position_id=data.fiscal_position_id,
            payment_term_id=data.payment_term_id,
        )
        self.db.add(move)
        await self.db.flush()
        await self.db.refresh(move)

        # Create lines
        if data.lines:
            for line_data in data.lines:
                await self._create_move_line(move, line_data)

        # For invoices, compute tax lines and totals
        if move.move_type in INVOICE_TYPES:
            await self._recompute_invoice(move)

        await self.db.flush()
        await self.db.refresh(move)

        await event_bus.publish("move.created", {
            "move_id": str(move.id),
            "move_type": move.move_type,
        })

        return move

    # ── Post ──────────────────────────────────────────────────────────

    async def post_move(self, move_id: uuid.UUID) -> Move:
        """Post a draft journal entry: validate, assign sequence, lock."""
        move = await self.move_repo.get_by_id_or_raise(move_id, "Move")

        if move.state != "draft":
            raise BusinessRuleError(f"Cannot post move in state '{move.state}'")

        # Validate balance
        await self._validate_balanced(move)

        # Validate all lines have accounts
        for line in move.lines:
            if not line.account_id:
                raise ValidationError(f"Line {line.id} is missing an account")

        # Assign sequence name
        journal = await self.journal_repo.get_by_id(move.journal_id)
        is_refund = move.move_type in ("out_refund", "in_refund")
        move.name = journal.generate_sequence_name(is_refund=is_refund)

        # Increment journal sequence
        if is_refund and journal.use_separate_refund_sequence:
            journal.refund_sequence_next_number += 1
        else:
            journal.sequence_next_number += 1

        # Set state
        move.state = "posted"

        # Set residual amounts on receivable/payable lines
        for line in move.lines:
            account = await self.account_repo.get_by_id(line.account_id)
            if account and account.account_type in MUST_RECONCILE_TYPES:
                line.amount_residual = line.balance
                line.amount_residual_currency = line.amount_currency

        # Compute hash for audit trail
        if journal.restrict_mode_hash_table:
            move.inalterable_hash = self._compute_hash(move)

        await self.db.flush()

        await event_bus.publish("move.posted", {
            "move_id": str(move.id),
            "name": move.name,
            "move_type": move.move_type,
        })

        return move

    # ── Cancel ────────────────────────────────────────────────────────

    async def cancel_move(self, move_id: uuid.UUID) -> Move:
        """Cancel a posted move (set to cancel state)."""
        move = await self.move_repo.get_by_id_or_raise(move_id, "Move")

        if move.state == "cancel":
            raise BusinessRuleError("Move is already cancelled")

        if move.state == "posted":
            # Check for reconciled lines
            for line in move.lines:
                if line.reconciled:
                    raise BusinessRuleError(
                        "Cannot cancel a move with reconciled lines. "
                        "Unreconcile first or create a reversal."
                    )

        move.state = "cancel"
        await self.db.flush()

        await event_bus.publish("move.cancelled", {"move_id": str(move.id)})
        return move

    # ── Reset to Draft ────────────────────────────────────────────────

    async def reset_to_draft(self, move_id: uuid.UUID) -> Move:
        """Reset a cancelled move back to draft."""
        move = await self.move_repo.get_by_id_or_raise(move_id, "Move")

        if move.state != "cancel":
            raise BusinessRuleError("Only cancelled moves can be reset to draft")

        move.state = "draft"
        await self.db.flush()
        return move

    # ── Reversal ──────────────────────────────────────────────────────

    async def create_reversal(
        self, move_id: uuid.UUID, *, reversal_date: date | None = None,
    ) -> Move:
        """Create a reversal entry for a posted move (credit note / reversal)."""
        original = await self.move_repo.get_by_id_or_raise(move_id, "Move")

        if original.state != "posted":
            raise BusinessRuleError("Can only reverse posted moves")

        # Determine reversal type
        type_map = {
            "out_invoice": "out_refund",
            "in_invoice": "in_refund",
            "out_refund": "out_invoice",
            "in_refund": "in_invoice",
        }
        reversal_type = type_map.get(original.move_type, "entry")

        reversal = Move(
            move_type=reversal_type,
            journal_id=original.journal_id,
            partner_id=original.partner_id,
            date=reversal_date or date.today(),
            currency_code=original.currency_code,
            currency_rate=original.currency_rate,
            ref=f"Reversal of {original.name}",
            reversed_entry_id=original.id,
        )
        self.db.add(reversal)
        await self.db.flush()

        # Create reversed lines (swap debit/credit)
        for line in original.lines:
            reversed_line = MoveLine(
                move_id=reversal.id,
                account_id=line.account_id,
                partner_id=line.partner_id,
                debit=line.credit,
                credit=line.debit,
                balance=-(line.balance),
                amount_currency=-(line.amount_currency),
                currency_code=line.currency_code,
                name=f"Reversal: {line.name or ''}",
                display_type=line.display_type,
                quantity=line.quantity,
                price_unit=line.price_unit,
                sequence=line.sequence,
            )
            self.db.add(reversed_line)

        # Recompute amounts
        reversal.amount_untaxed = original.amount_untaxed
        reversal.amount_tax = original.amount_tax
        reversal.amount_total = original.amount_total
        await self.db.flush()
        await self.db.refresh(reversal)

        await event_bus.publish("move.reversed", {
            "move_id": str(reversal.id),
            "original_move_id": str(original.id),
        })

        return reversal

    # ── Update ────────────────────────────────────────────────────────

    async def update_move(self, move_id: uuid.UUID, data: MoveUpdate) -> Move:
        """Update a draft move."""
        move = await self.move_repo.get_by_id_or_raise(move_id, "Move")

        if move.state != "draft":
            raise BusinessRuleError("Can only edit moves in draft state")

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(move, key, value)

        await self.db.flush()
        await self.db.refresh(move)
        return move

    # ── Private helpers ───────────────────────────────────────────────

    async def _create_move_line(self, move: Move, data: MoveLineCreate) -> MoveLine:
        """Create a single move line."""
        # Validate account exists
        account = await self.account_repo.get_by_id(data.account_id)
        if not account:
            raise NotFoundError("Account", str(data.account_id))

        # Compute balance
        debit = data.debit or 0.0
        credit = data.credit or 0.0

        # For invoice product lines, compute from price
        if data.display_type == "product" and data.price_unit:
            subtotal = data.quantity * data.price_unit * (1 - (data.discount or 0) / 100)
            if move.direction_sign > 0:
                debit = max(subtotal, 0)
                credit = max(-subtotal, 0)
            else:
                debit = max(-subtotal, 0)
                credit = max(subtotal, 0)

        line = MoveLine(
            move_id=move.id,
            account_id=data.account_id,
            partner_id=data.partner_id or move.partner_id,
            debit=round(debit, 2),
            credit=round(credit, 2),
            balance=round(debit - credit, 2),
            amount_currency=data.amount_currency or round(debit - credit, 2),
            currency_code=data.currency_code or move.currency_code,
            name=data.name,
            display_type=data.display_type or "product",
            product_id=data.product_id,
            quantity=data.quantity or 1.0,
            price_unit=data.price_unit or 0.0,
            discount=data.discount or 0.0,
            price_subtotal=round((data.quantity or 1) * (data.price_unit or 0) * (1 - (data.discount or 0) / 100), 2),
            sequence=data.sequence or 10,
            date_maturity=data.date_maturity,
        )

        self.db.add(line)
        await self.db.flush()
        return line

    async def _recompute_invoice(self, move: Move) -> None:
        """Recompute tax lines and totals for an invoice move."""
        product_lines = [l for l in move.lines if l.display_type == "product"]

        amount_untaxed = 0.0
        amount_tax = 0.0

        for line in product_lines:
            subtotal = line.quantity * line.price_unit * (1 - line.discount / 100)
            line.price_subtotal = round(subtotal, 2)
            amount_untaxed += line.price_subtotal

            # Compute taxes if any
            if line.tax_ids:
                tax_result = await self.tax_svc.compute_taxes(
                    [t.id for t in line.tax_ids],
                    line.price_unit,
                    line.quantity,
                    is_refund=move.move_type in ("out_refund", "in_refund"),
                )
                line.price_total = tax_result.price_total
                amount_tax += tax_result.total_tax
            else:
                line.price_total = line.price_subtotal

        move.amount_untaxed = round(amount_untaxed, 2)
        move.amount_tax = round(amount_tax, 2)
        move.amount_total = round(amount_untaxed + amount_tax, 2)
        move.amount_residual = move.amount_total

    async def _validate_balanced(self, move: Move) -> None:
        """Validate that total debits = total credits."""
        total_debit = sum(l.debit for l in move.lines)
        total_credit = sum(l.credit for l in move.lines)

        if abs(total_debit - total_credit) > 0.01:
            raise BusinessRuleError(
                f"Journal entry is not balanced: "
                f"debits ({total_debit:.2f}) != credits ({total_credit:.2f})"
            )

    def _compute_hash(self, move: Move) -> str:
        """Compute inalterable hash for audit trail."""
        data = f"{move.name}|{move.date}|{move.amount_total}|{move.journal_id}"
        return hashlib.sha256(data.encode()).hexdigest()
