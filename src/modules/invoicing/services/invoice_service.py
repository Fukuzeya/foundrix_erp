"""Invoice service — high-level operations for customer invoices, vendor bills, and credit notes.

Wraps the accounting MoveService with invoice-specific workflows:
- Customer invoice / vendor bill creation from simplified schemas
- Credit note generation (full reversal)
- Invoice duplication
- Payment registration against invoices
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move, INVOICE_TYPES
from src.modules.accounting.repositories.journal_repo import JournalRepository
from src.modules.accounting.repositories.move_repo import MoveRepository
from src.modules.accounting.schemas.move import MoveCreate, MoveLineCreate
from src.modules.accounting.services.move_service import MoveService
from src.modules.accounting.services.payment_service import PaymentService
from src.modules.accounting.schemas.payment import PaymentCreate
from src.modules.invoicing.schemas.invoice import (
    CreateCustomerInvoice,
    CreateVendorBill,
    CreateCreditNote,
    DuplicateInvoice,
    RegisterPaymentRequest,
)

logger = logging.getLogger(__name__)


class InvoiceService:
    """High-level invoice operations built on top of accounting moves."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_svc = MoveService(db)
        self.payment_svc = PaymentService(db)
        self.move_repo = MoveRepository(db)
        self.journal_repo = JournalRepository(db)

    # ── Customer Invoice ──────────────────────────────────────────────

    async def create_customer_invoice(self, data: CreateCustomerInvoice) -> Move:
        """Create a customer invoice (out_invoice) in draft state."""
        journal_id = data.journal_id
        if not journal_id:
            journal_id = await self._find_journal_by_type("sale")

        lines = [
            MoveLineCreate(
                account_id=line.account_id,
                product_id=line.product_id,
                name=line.name,
                quantity=line.quantity,
                price_unit=line.price_unit,
                discount=line.discount,
                display_type="product",
            )
            for line in data.lines
        ]

        move_data = MoveCreate(
            move_type="out_invoice",
            journal_id=journal_id,
            partner_id=data.partner_id,
            date=data.invoice_date or date.today(),
            invoice_date=data.invoice_date,
            invoice_date_due=data.invoice_date_due,
            currency_code=data.currency_code,
            payment_term_id=data.payment_term_id,
            fiscal_position_id=data.fiscal_position_id,
            ref=data.ref,
            narration=data.narration,
            lines=lines,
        )

        move = await self.move_svc.create_move(move_data)

        await event_bus.publish("invoice.customer_created", {
            "move_id": str(move.id),
            "partner_id": str(data.partner_id),
        })

        return move

    # ── Vendor Bill ───────────────────────────────────────────────────

    async def create_vendor_bill(self, data: CreateVendorBill) -> Move:
        """Create a vendor bill (in_invoice) in draft state."""
        journal_id = data.journal_id
        if not journal_id:
            journal_id = await self._find_journal_by_type("purchase")

        lines = [
            MoveLineCreate(
                account_id=line.account_id,
                product_id=line.product_id,
                name=line.name,
                quantity=line.quantity,
                price_unit=line.price_unit,
                discount=line.discount,
                display_type="product",
            )
            for line in data.lines
        ]

        move_data = MoveCreate(
            move_type="in_invoice",
            journal_id=journal_id,
            partner_id=data.partner_id,
            date=data.invoice_date or date.today(),
            invoice_date=data.invoice_date,
            invoice_date_due=data.invoice_date_due,
            currency_code=data.currency_code,
            payment_term_id=data.payment_term_id,
            fiscal_position_id=data.fiscal_position_id,
            ref=data.ref,
            narration=data.narration,
            lines=lines,
        )

        move = await self.move_svc.create_move(move_data)

        await event_bus.publish("invoice.vendor_bill_created", {
            "move_id": str(move.id),
            "partner_id": str(data.partner_id),
        })

        return move

    # ── Credit Note ───────────────────────────────────────────────────

    async def create_credit_note(self, data: CreateCreditNote) -> Move:
        """Create a credit note (reversal) for an existing posted invoice."""
        original = await self.move_repo.get_by_id(data.invoice_id)
        if not original:
            raise NotFoundError("Invoice", str(data.invoice_id))

        if original.state != "posted":
            raise BusinessRuleError("Can only create credit notes for posted invoices")

        if original.move_type not in INVOICE_TYPES:
            raise BusinessRuleError("Can only create credit notes for invoice-type moves")

        reversal = await self.move_svc.create_reversal(
            data.invoice_id,
            reversal_date=data.reversal_date,
        )

        if data.reason:
            reversal.ref = f"Credit Note: {data.reason}"
            await self.db.flush()

        await event_bus.publish("invoice.credit_note_created", {
            "move_id": str(reversal.id),
            "original_move_id": str(data.invoice_id),
            "reason": data.reason,
        })

        return reversal

    # ── Duplicate ─────────────────────────────────────────────────────

    async def duplicate_invoice(self, data: DuplicateInvoice) -> Move:
        """Duplicate an existing invoice as a new draft."""
        original = await self.move_repo.get_by_id(data.invoice_id)
        if not original:
            raise NotFoundError("Invoice", str(data.invoice_id))

        if original.move_type not in INVOICE_TYPES:
            raise BusinessRuleError("Can only duplicate invoice-type moves")

        # Re-create lines from original
        lines = [
            MoveLineCreate(
                account_id=line.account_id,
                product_id=line.product_id,
                name=line.name,
                quantity=line.quantity,
                price_unit=line.price_unit,
                discount=line.discount,
                display_type=line.display_type,
                sequence=line.sequence,
            )
            for line in original.lines
            if line.display_type == "product"
        ]

        move_data = MoveCreate(
            move_type=original.move_type,
            journal_id=original.journal_id,
            partner_id=original.partner_id,
            date=data.new_date or date.today(),
            invoice_date=data.new_date or date.today(),
            currency_code=original.currency_code,
            payment_term_id=original.payment_term_id,
            fiscal_position_id=original.fiscal_position_id,
            ref=f"Duplicate of {original.name or original.id}",
            narration=original.narration,
            lines=lines,
        )

        new_move = await self.move_svc.create_move(move_data)

        await event_bus.publish("invoice.duplicated", {
            "move_id": str(new_move.id),
            "original_move_id": str(data.invoice_id),
        })

        return new_move

    # ── Register Payment ──────────────────────────────────────────────

    async def register_payment(self, data: RegisterPaymentRequest) -> Move:
        """Register a payment against one or more invoices."""
        # Validate invoices exist and are posted
        for inv_id in data.invoice_ids:
            invoice = await self.move_repo.get_by_id(inv_id)
            if not invoice:
                raise NotFoundError("Invoice", str(inv_id))
            if invoice.state != "posted":
                raise BusinessRuleError(
                    f"Invoice {invoice.name or inv_id} is not posted"
                )
            if invoice.amount_residual <= 0:
                raise BusinessRuleError(
                    f"Invoice {invoice.name or inv_id} is already fully paid"
                )

        # Determine payment type from first invoice
        first_invoice = await self.move_repo.get_by_id(data.invoice_ids[0]) if data.invoice_ids else None
        if first_invoice and first_invoice.move_type in ("out_invoice", "out_refund"):
            payment_type = "inbound"
            partner_type = "customer"
        else:
            payment_type = "outbound"
            partner_type = "supplier"

        payment_data = PaymentCreate(
            payment_type=payment_type,
            partner_type=partner_type,
            partner_id=data.partner_id,
            journal_id=data.journal_id,
            amount=data.amount,
            currency_code=data.currency_code,
            date=data.payment_date,
            memo=data.memo,
            invoice_ids=data.invoice_ids,
        )

        payment = await self.payment_svc.create_payment(payment_data)
        confirmed = await self.payment_svc.confirm_payment(payment.id)

        return confirmed

    # ── Confirm / Post ────────────────────────────────────────────────

    async def confirm_invoice(self, invoice_id: uuid.UUID) -> Move:
        """Confirm (post) a draft invoice."""
        return await self.move_svc.post_move(invoice_id)

    async def cancel_invoice(self, invoice_id: uuid.UUID) -> Move:
        """Cancel a posted invoice."""
        return await self.move_svc.cancel_move(invoice_id)

    async def reset_to_draft(self, invoice_id: uuid.UUID) -> Move:
        """Reset a cancelled invoice to draft."""
        return await self.move_svc.reset_to_draft(invoice_id)

    # ── Helpers ───────────────────────────────────────────────────────

    async def _find_journal_by_type(self, journal_type: str) -> uuid.UUID:
        """Find the default journal for a given type (sale/purchase)."""
        journals = await self.journal_repo.get_by_type(journal_type)
        if not journals:
            raise BusinessRuleError(
                f"No {journal_type} journal found. Please create one first."
            )
        return journals[0].id
