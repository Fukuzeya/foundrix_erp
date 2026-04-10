"""Cash Basis Tax service — recognizes tax on payment rather than on invoice.

When a tax has ``tax_exigibility = 'on_payment'``, the tax amount is initially
parked in a transition account on invoicing. When the invoice is paid (fully or
partially), a cash basis entry moves the proportional tax from the transition
account to the final tax account.

Flow:
1. Invoice posted with cash-basis tax -> tax posted to transition account
2. Payment reconciled against invoice -> this service creates a proportional
   entry moving tax from transition to final account
3. Payment unreconciled -> this service reverses the cash basis entries
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move, MoveLine, INVOICE_TYPES
from src.modules.accounting.models.payment import Payment
from src.modules.accounting.models.tax import Tax, TaxRepartitionLine
from src.modules.accounting.repositories.journal_repo import JournalRepository
from src.modules.accounting.repositories.move_repo import MoveRepository, MoveLineRepository
from src.modules.accounting.repositories.payment_repo import PaymentRepository
from src.modules.accounting.repositories.tax_repo import TaxRepository

logger = logging.getLogger(__name__)

# Ref prefix for cash basis entries so they can be identified and reversed
_CB_REF_PREFIX = "CBTAX/"


class CashBasisService:
    """Generates and reverses cash basis tax entries when payments are reconciled."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_repo = MoveRepository(db)
        self.line_repo = MoveLineRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.journal_repo = JournalRepository(db)
        self.tax_repo = TaxRepository(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_cash_basis_entries(
        self, payment_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Generate cash basis tax entries when a payment is reconciled against invoices.

        For each invoice linked to the payment, inspects all tax lines where the
        underlying tax has ``tax_exigibility == 'on_payment'``. For each such
        line, creates a proportional journal entry that:
        - Debits the cash-basis transition account (reversing the parking entry)
        - Credits the final tax account (recognizing the real tax)

        The proportion is ``payment_amount / invoice_total``, clamped to the
        remaining unrecognised tax.

        Returns:
            List of created ``Move.id`` values.
        """
        payment = await self._get_payment(payment_id)

        if payment.state not in ("posted", "reconciled"):
            raise BusinessRuleError(
                "Cash basis entries can only be generated for posted or reconciled payments"
            )

        invoices = await self._get_linked_invoices(payment)
        if not invoices:
            return []

        created_move_ids: list[uuid.UUID] = []

        for invoice in invoices:
            move_ids = await self._generate_for_invoice(payment, invoice)
            created_move_ids.extend(move_ids)

        if created_move_ids:
            await self.db.flush()
            await event_bus.publish("cash_basis.entries_created", {
                "payment_id": str(payment_id),
                "move_ids": [str(mid) for mid in created_move_ids],
            })

        return created_move_ids

    async def reverse_cash_basis_entries(
        self, payment_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Reverse all cash basis entries previously generated for a payment.

        Finds every move whose ``ref`` starts with ``CBTAX/<payment_id>`` and
        creates a reversal for each (swapping debit/credit). The original
        entries are marked as cancelled.

        Returns:
            List of reversal ``Move.id`` values.
        """
        payment = await self._get_payment(payment_id)
        ref_pattern = f"{_CB_REF_PREFIX}{payment.id}"

        # Find all cash basis moves for this payment
        result = await self.db.execute(
            select(Move).where(
                Move.ref.like(f"{ref_pattern}%"),
                Move.state == "posted",
            )
        )
        cb_moves = list(result.scalars().all())

        if not cb_moves:
            return []

        reversal_ids: list[uuid.UUID] = []

        for original in cb_moves:
            reversal = await self._create_reversal(original, payment.date)
            reversal_ids.append(reversal.id)
            # Cancel the original
            original.state = "cancel"

        await self.db.flush()

        await event_bus.publish("cash_basis.entries_reversed", {
            "payment_id": str(payment_id),
            "reversal_move_ids": [str(mid) for mid in reversal_ids],
        })

        return reversal_ids

    async def get_cash_basis_report(
        self, date_from: date, date_to: date,
    ) -> dict:
        """Report showing cash basis tax movements within a period.

        Returns a summary dict containing:
        - ``period``: the requested date range
        - ``total_recognised``: total tax moved from transition to final accounts
        - ``total_reversed``: total tax reversed (unreconciliations)
        - ``by_tax``: breakdown per tax, each with recognised/reversed/net amounts
        - ``entries``: list of individual cash basis move summaries
        """
        # Fetch all posted cash basis entries in the period
        result = await self.db.execute(
            select(Move).where(
                Move.ref.like(f"{_CB_REF_PREFIX}%"),
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
            ).order_by(Move.date)
        )
        cb_moves = list(result.scalars().all())

        total_recognised = 0.0
        total_reversed = 0.0
        tax_breakdown: dict[str, dict] = {}
        entries: list[dict] = []

        for move in cb_moves:
            is_reversal = move.reversed_entry_id is not None

            # Sum the tax-side lines (credit lines on normal entries = tax recognised)
            tax_amount = 0.0
            tax_id_str: str | None = None

            for line in move.lines:
                if line.tax_line_id:
                    tax_amount += abs(line.balance)
                    tax_id_str = str(line.tax_line_id)

            if is_reversal:
                total_reversed += tax_amount
            else:
                total_recognised += tax_amount

            # Aggregate by tax
            if tax_id_str:
                if tax_id_str not in tax_breakdown:
                    tax_breakdown[tax_id_str] = {
                        "tax_id": tax_id_str,
                        "recognised": 0.0,
                        "reversed": 0.0,
                    }
                if is_reversal:
                    tax_breakdown[tax_id_str]["reversed"] += tax_amount
                else:
                    tax_breakdown[tax_id_str]["recognised"] += tax_amount

            entries.append({
                "move_id": str(move.id),
                "move_name": move.name,
                "date": move.date.isoformat(),
                "ref": move.ref,
                "amount": round(tax_amount, 2),
                "is_reversal": is_reversal,
            })

        # Compute net for each tax
        by_tax = []
        for info in tax_breakdown.values():
            info["net"] = round(info["recognised"] - info["reversed"], 2)
            info["recognised"] = round(info["recognised"], 2)
            info["reversed"] = round(info["reversed"], 2)
            by_tax.append(info)

        return {
            "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            "total_recognised": round(total_recognised, 2),
            "total_reversed": round(total_reversed, 2),
            "net": round(total_recognised - total_reversed, 2),
            "by_tax": by_tax,
            "entries": entries,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_payment(self, payment_id: uuid.UUID) -> Payment:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise NotFoundError("Payment", str(payment_id))
        return payment

    async def _get_linked_invoices(self, payment: Payment) -> list[Move]:
        """Return posted invoices linked to a payment."""
        invoices: list[Move] = []
        for inv in (payment.invoice_ids or []):
            move = inv if isinstance(inv, Move) else await self.move_repo.get_by_id(inv)
            if move and move.state == "posted" and move.move_type in INVOICE_TYPES:
                invoices.append(move)
        return invoices

    async def _generate_for_invoice(
        self, payment: Payment, invoice: Move,
    ) -> list[uuid.UUID]:
        """Generate cash basis entries for one invoice relative to a payment.

        The payment ratio is ``min(payment_amount, invoice_total) / invoice_total``.
        We also subtract any previously recognised amount (from prior partial
        payments) so we never exceed 100 %.
        """
        if invoice.amount_total == 0:
            return []

        # Compute payment ratio for this invoice
        payment_toward_invoice = min(payment.amount, invoice.amount_total)
        payment_ratio = payment_toward_invoice / invoice.amount_total

        # Collect tax lines with cash-basis exigibility
        cash_basis_lines = await self._collect_cash_basis_tax_lines(invoice)
        if not cash_basis_lines:
            return []

        # Determine journal for the cash basis entries (use the invoice's journal,
        # or fall back to the first general journal)
        journal = await self.journal_repo.get_by_id(invoice.journal_id)
        if not journal:
            raise NotFoundError("Journal", str(invoice.journal_id))

        created: list[uuid.UUID] = []

        for tax_line, tax in cash_basis_lines:
            # Amount to recognise this time
            full_tax_amount = abs(tax_line.balance)
            recognise_amount = round(full_tax_amount * payment_ratio, 2)

            if recognise_amount < 0.01:
                continue

            # Already recognised for this invoice+tax via prior payments
            already_recognised = await self._already_recognised(
                invoice.id, tax.id,
            )
            remaining = round(full_tax_amount - already_recognised, 2)
            recognise_amount = min(recognise_amount, remaining)

            if recognise_amount < 0.01:
                continue

            transition_account_id = tax.cash_basis_transition_account_id
            if not transition_account_id:
                logger.warning(
                    "Tax %s (%s) is cash-basis but has no transition account; skipping",
                    tax.id, tax.name,
                )
                continue

            # Find the final tax account from the repartition lines
            final_account_id = await self._get_final_tax_account(tax, invoice)
            if not final_account_id:
                logger.warning(
                    "Tax %s (%s) has no repartition tax account; skipping",
                    tax.id, tax.name,
                )
                continue

            # Determine debit/credit direction: on the original invoice the tax
            # was posted to the transition account. We now reverse that and post
            # to the final account.
            #   Original invoice tax line: debit transition (for purchase) or
            #   credit transition (for sale).  We reverse that and post to the
            #   final account.
            is_sale = invoice.move_type in ("out_invoice", "out_refund")

            move = Move(
                move_type="entry",
                journal_id=journal.id,
                partner_id=invoice.partner_id,
                date=payment.date,
                ref=f"{_CB_REF_PREFIX}{payment.id}/{invoice.id}/{tax.id}",
                narration=(
                    f"Cash basis tax recognition: {tax.name} "
                    f"({recognise_amount:.2f}) for invoice {invoice.name}"
                ),
                currency_code=invoice.currency_code,
                currency_rate=invoice.currency_rate,
                state="posted",
            )
            self.db.add(move)
            await self.db.flush()

            # Assign a sequence name
            journal_obj = await self.journal_repo.get_by_id(journal.id)
            move.name = journal_obj.generate_sequence_name()
            journal_obj.sequence_next_number += 1

            # Line 1: reverse the transition account
            if is_sale:
                # Sale invoice: tax was credited to transition; now debit it
                transition_line = MoveLine(
                    move_id=move.id,
                    account_id=transition_account_id,
                    partner_id=invoice.partner_id,
                    debit=recognise_amount,
                    credit=0.0,
                    balance=recognise_amount,
                    name=f"Cash basis: {tax.name} (transition)",
                    display_type="tax",
                    tax_line_id=tax.id,
                    tax_base_amount=round(tax_line.tax_base_amount * payment_ratio, 2),
                )
                # Line 2: recognise in the final tax account
                final_line = MoveLine(
                    move_id=move.id,
                    account_id=final_account_id,
                    partner_id=invoice.partner_id,
                    debit=0.0,
                    credit=recognise_amount,
                    balance=-recognise_amount,
                    name=f"Cash basis: {tax.name} (recognised)",
                    display_type="tax",
                    tax_line_id=tax.id,
                    tax_base_amount=round(tax_line.tax_base_amount * payment_ratio, 2),
                )
            else:
                # Purchase invoice: tax was debited to transition; now credit it
                transition_line = MoveLine(
                    move_id=move.id,
                    account_id=transition_account_id,
                    partner_id=invoice.partner_id,
                    debit=0.0,
                    credit=recognise_amount,
                    balance=-recognise_amount,
                    name=f"Cash basis: {tax.name} (transition)",
                    display_type="tax",
                    tax_line_id=tax.id,
                    tax_base_amount=round(tax_line.tax_base_amount * payment_ratio, 2),
                )
                final_line = MoveLine(
                    move_id=move.id,
                    account_id=final_account_id,
                    partner_id=invoice.partner_id,
                    debit=recognise_amount,
                    credit=0.0,
                    balance=recognise_amount,
                    name=f"Cash basis: {tax.name} (recognised)",
                    display_type="tax",
                    tax_line_id=tax.id,
                    tax_base_amount=round(tax_line.tax_base_amount * payment_ratio, 2),
                )

            self.db.add(transition_line)
            self.db.add(final_line)

            move.amount_total = recognise_amount
            await self.db.flush()

            created.append(move.id)

        return created

    async def _collect_cash_basis_tax_lines(
        self, invoice: Move,
    ) -> list[tuple[MoveLine, Tax]]:
        """Return (move_line, tax) pairs for tax lines with cash-basis exigibility."""
        pairs: list[tuple[MoveLine, Tax]] = []

        for line in invoice.lines:
            if line.display_type != "tax" or not line.tax_line_id:
                continue

            tax = await self.tax_repo.get_by_id(line.tax_line_id)
            if not tax:
                continue

            if tax.tax_exigibility == "on_payment":
                pairs.append((line, tax))

        return pairs

    async def _get_final_tax_account(
        self, tax: Tax, invoice: Move,
    ) -> uuid.UUID | None:
        """Determine the final tax account from repartition lines.

        Uses invoice repartition for normal invoices and refund repartition
        for credit notes.
        """
        is_refund = invoice.move_type in ("out_refund", "in_refund")
        repartition_lines = (
            tax.refund_repartition_lines if is_refund
            else tax.invoice_repartition_lines
        )

        for rep_line in repartition_lines:
            if rep_line.repartition_type == "tax" and rep_line.account_id:
                return rep_line.account_id

        return None

    async def _already_recognised(
        self, invoice_id: uuid.UUID, tax_id: uuid.UUID,
    ) -> float:
        """Sum of tax amounts already recognised for an invoice+tax combination.

        Looks at posted cash basis moves whose ref encodes the invoice and tax.
        """
        ref_pattern = f"{_CB_REF_PREFIX}%/{invoice_id}/{tax_id}"
        result = await self.db.execute(
            select(Move).where(
                Move.ref.like(ref_pattern),
                Move.state == "posted",
            )
        )
        cb_moves = list(result.scalars().all())

        total = 0.0
        for move in cb_moves:
            for line in move.lines:
                if line.tax_line_id == tax_id:
                    total += abs(line.balance)
            # Only count half since the entry has both sides
            # Actually each entry has two lines of equal amount, but only one
            # per tax_line_id side. The absolute balance of that line is the
            # recognised amount.
        # Each move's tax_line amount represents the full recognised amount
        # for that entry (the other line is the transition reversal).
        return round(total / 2, 2) if cb_moves else 0.0

    async def _create_reversal(self, original: Move, reversal_date: date) -> Move:
        """Create a reversal move that swaps debit/credit of the original."""
        reversal = Move(
            move_type="entry",
            journal_id=original.journal_id,
            partner_id=original.partner_id,
            date=reversal_date,
            ref=f"{original.ref}/REV",
            narration=f"Reversal of cash basis entry {original.name}",
            currency_code=original.currency_code,
            currency_rate=original.currency_rate,
            reversed_entry_id=original.id,
            state="posted",
        )
        self.db.add(reversal)
        await self.db.flush()

        # Assign sequence
        journal = await self.journal_repo.get_by_id(original.journal_id)
        reversal.name = journal.generate_sequence_name()
        journal.sequence_next_number += 1

        # Create reversed lines
        for line in original.lines:
            reversed_line = MoveLine(
                move_id=reversal.id,
                account_id=line.account_id,
                partner_id=line.partner_id,
                debit=line.credit,
                credit=line.debit,
                balance=-line.balance,
                amount_currency=-line.amount_currency,
                currency_code=line.currency_code,
                name=f"Reversal: {line.name or ''}",
                display_type=line.display_type,
                tax_line_id=line.tax_line_id,
                tax_base_amount=line.tax_base_amount,
                sequence=line.sequence,
            )
            self.db.add(reversed_line)

        reversal.amount_total = original.amount_total
        await self.db.flush()

        return reversal
