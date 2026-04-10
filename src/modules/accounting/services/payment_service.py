"""Payment service — handles payment creation and invoice reconciliation.

Supports:
- Inbound payments (customer payments)
- Outbound payments (vendor payments)
- Internal transfers between journals
- Batch payments for grouped processing
- Automatic reconciliation with invoices
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move, MoveLine
from src.modules.accounting.models.payment import Payment, BatchPayment
from src.modules.accounting.repositories.journal_repo import JournalRepository
from src.modules.accounting.repositories.move_repo import MoveRepository
from src.modules.accounting.repositories.payment_repo import (
    PaymentRepository,
    BatchPaymentRepository,
)
from src.modules.accounting.schemas.payment import PaymentCreate

logger = logging.getLogger(__name__)


class PaymentService:
    """Manages payment registration and invoice reconciliation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.payment_repo = PaymentRepository(db)
        self.move_repo = MoveRepository(db)
        self.journal_repo = JournalRepository(db)
        self.batch_repo = BatchPaymentRepository(db)

    def build_filtered_query(self, **kwargs):
        """Delegate filtered query construction to the payment repository."""
        return self.payment_repo.build_filtered_query(**kwargs)

    async def get_payment(self, payment_id: uuid.UUID) -> Payment:
        """Get a payment by ID."""
        return await self.payment_repo.get_by_id_or_raise(payment_id, "Payment")

    async def create_payment(self, data: PaymentCreate) -> Payment:
        """Create a payment record."""
        journal = await self.journal_repo.get_by_id(data.journal_id)
        if not journal:
            raise NotFoundError("Journal", str(data.journal_id))

        if journal.journal_type not in ("bank", "cash"):
            raise BusinessRuleError("Payments must use a bank or cash journal")

        payment = Payment(
            payment_type=data.payment_type,
            partner_type=data.partner_type,
            partner_id=data.partner_id,
            journal_id=data.journal_id,
            amount=data.amount,
            currency_code=data.currency_code or journal.currency_code or "USD",
            date=data.date or date.today(),
            ref=data.ref,
            memo=data.memo,
            payment_method_id=data.payment_method_id,
            destination_journal_id=data.destination_journal_id,
        )
        self.db.add(payment)
        await self.db.flush()
        await self.db.refresh(payment)

        await event_bus.publish("payment.created", {
            "payment_id": str(payment.id),
            "payment_type": payment.payment_type,
            "amount": payment.amount,
        })

        return payment

    async def confirm_payment(self, payment_id: uuid.UUID) -> Payment:
        """Confirm a draft payment — generates journal entry and reconciles."""
        payment = await self.payment_repo.get_by_id_or_raise(payment_id, "Payment")

        if payment.state != "draft":
            raise BusinessRuleError(f"Cannot confirm payment in state '{payment.state}'")

        journal = await self.journal_repo.get_by_id(payment.journal_id)
        if not journal:
            raise NotFoundError("Journal", str(payment.journal_id))

        # Generate journal entry for the payment
        move = await self._create_payment_move(payment, journal)
        payment.move_id = move.id
        payment.state = "posted"
        payment.name = move.name

        await self.db.flush()

        # Auto-reconcile with outstanding invoices
        if payment.invoice_ids:
            await self._reconcile_with_invoices(payment)

        await event_bus.publish("payment.confirmed", {
            "payment_id": str(payment.id),
            "move_id": str(move.id),
        })

        return payment

    async def cancel_payment(self, payment_id: uuid.UUID) -> Payment:
        """Cancel a confirmed payment."""
        payment = await self.payment_repo.get_by_id_or_raise(payment_id, "Payment")

        if payment.state != "posted":
            raise BusinessRuleError("Can only cancel posted payments")

        payment.state = "cancel"

        # Cancel the associated move
        if payment.move_id:
            move = await self.move_repo.get_by_id(payment.move_id)
            if move and move.state == "posted":
                move.state = "cancel"

        await self.db.flush()

        await event_bus.publish("payment.cancelled", {"payment_id": str(payment.id)})
        return payment

    async def _create_payment_move(self, payment: Payment, journal) -> Move:
        """Create the journal entry for a payment."""
        from src.modules.accounting.services.move_service import MoveService

        move_svc = MoveService(self.db)

        # Determine accounts
        liquidity_account_id = journal.default_account_id
        if not liquidity_account_id:
            raise BusinessRuleError(f"Journal '{journal.name}' has no default account configured")

        # For customer payment: Debit Bank, Credit Receivable
        # For vendor payment: Debit Payable, Credit Bank
        from src.modules.accounting.repositories.account_repo import AccountRepository
        acct_repo = AccountRepository(self.db)

        if payment.payment_type == "inbound":
            # Customer payment
            counterpart_accounts = await acct_repo.get_by_internal_group("asset")
            receivable = [a for a in counterpart_accounts if a.account_type == "asset_receivable"]
            counterpart_account_id = receivable[0].id if receivable else liquidity_account_id
        else:
            # Vendor payment
            counterpart_accounts = await acct_repo.get_by_internal_group("liability")
            payable = [a for a in counterpart_accounts if a.account_type == "liability_payable"]
            counterpart_account_id = payable[0].id if payable else liquidity_account_id

        move = Move(
            move_type="entry",
            journal_id=payment.journal_id,
            partner_id=payment.partner_id,
            date=payment.date,
            ref=payment.ref or payment.memo,
            currency_code=payment.currency_code,
        )
        self.db.add(move)
        await self.db.flush()

        # Create debit/credit lines
        if payment.payment_type == "inbound":
            debit_account = liquidity_account_id
            credit_account = counterpart_account_id
        else:
            debit_account = counterpart_account_id
            credit_account = liquidity_account_id

        debit_line = MoveLine(
            move_id=move.id,
            account_id=debit_account,
            partner_id=payment.partner_id,
            debit=payment.amount,
            credit=0.0,
            balance=payment.amount,
            name=f"Payment: {payment.ref or payment.memo or ''}",
            display_type="payment_term",
        )
        credit_line = MoveLine(
            move_id=move.id,
            account_id=credit_account,
            partner_id=payment.partner_id,
            debit=0.0,
            credit=payment.amount,
            balance=-payment.amount,
            name=f"Payment: {payment.ref or payment.memo or ''}",
            display_type="payment_term",
        )
        self.db.add(debit_line)
        self.db.add(credit_line)

        # Post the move
        move.state = "posted"
        journal_obj = await self.journal_repo.get_by_id(payment.journal_id)
        move.name = journal_obj.generate_sequence_name()
        journal_obj.sequence_next_number += 1

        move.amount_total = payment.amount
        await self.db.flush()

        return move

    async def _reconcile_with_invoices(self, payment: Payment) -> None:
        """Auto-reconcile payment with linked invoices."""
        from src.modules.accounting.services.reconciliation_service import ReconciliationService
        recon_svc = ReconciliationService(self.db)

        remaining = payment.amount
        for invoice_id in (payment.invoice_ids or []):
            if remaining <= 0:
                break

            invoice = await self.move_repo.get_by_id(invoice_id)
            if not invoice or invoice.state != "posted":
                continue

            reconcile_amount = min(remaining, invoice.amount_residual)
            if reconcile_amount > 0:
                # Find matching lines
                payment_lines = [l for l in (await self.move_repo.get_by_id(payment.move_id)).lines
                                 if l.credit > 0 or l.debit > 0]
                invoice_lines = [l for l in invoice.lines
                                 if not l.reconciled and l.amount_residual != 0]

                # Simple auto-reconciliation
                for inv_line in invoice_lines:
                    for pay_line in payment_lines:
                        if inv_line.account_id == pay_line.account_id:
                            await recon_svc.create_partial_reconcile(
                                debit_line=inv_line if inv_line.debit > 0 else pay_line,
                                credit_line=pay_line if pay_line.credit > 0 else inv_line,
                                amount=min(abs(inv_line.amount_residual), abs(pay_line.amount_residual)),
                            )

                remaining -= reconcile_amount
