"""Batch payment service — manages batch payment lifecycle.

Supports creating batches, adding lines (manually or from invoices),
confirming, executing (creating individual Payment records), and cancelling.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move
from src.modules.accounting.repositories.move_repo import MoveRepository
from src.modules.accounting.schemas.payment import PaymentCreate
from src.modules.accounting.services.payment_service import PaymentService
from src.modules.invoicing.models.batch_payment import (
    BatchPaymentLine,
    InvoiceBatchPayment,
)
from src.modules.invoicing.repositories.batch_payment_repo import (
    BatchPaymentLineRepository,
    InvoiceBatchPaymentRepository,
)
from src.modules.invoicing.schemas.batch_payment import (
    BatchPaymentCreate,
    BatchPaymentLineCreate,
)

logger = logging.getLogger(__name__)


class BatchPaymentService:
    """Manages invoice batch payment lifecycle."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.batch_repo = InvoiceBatchPaymentRepository(db)
        self.line_repo = BatchPaymentLineRepository(db)
        self.move_repo = MoveRepository(db)
        self.payment_service = PaymentService(db)

    # ── Queries ────────────────────────────────────────────────────────

    async def get_batch(self, batch_id: uuid.UUID) -> InvoiceBatchPayment:
        """Get a batch payment by ID with lines."""
        return await self.batch_repo.get_with_lines_or_raise(batch_id)

    async def list_batches(
        self,
        state: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[InvoiceBatchPayment]:
        """List batch payments, optionally filtered by state."""
        if state:
            return await self.batch_repo.list_by_state(
                state, offset=offset, limit=limit,
            )
        return await self.batch_repo.list_all(offset=offset, limit=limit)

    async def get_batch_summary(
        self, batch_id: uuid.UUID,
    ) -> InvoiceBatchPayment:
        """Get batch payment summary (same as get_batch; schema controls output)."""
        return await self.batch_repo.get_with_lines_or_raise(batch_id)

    # ── Batch Creation ─────────────────────────────────────────────────

    async def create_batch(
        self, data: BatchPaymentCreate,
    ) -> InvoiceBatchPayment:
        """Create a new batch payment in draft state."""
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        name = f"BATCH/{data.batch_type.upper()}/{timestamp}"

        batch = InvoiceBatchPayment(
            name=name,
            batch_type=data.batch_type,
            payment_method=data.payment_method,
            journal_id=data.journal_id,
            currency_code=data.currency_code,
            execution_date=data.execution_date,
            note=data.note,
            state="draft",
            total_amount=0.0,
            payment_count=0,
        )
        self.db.add(batch)
        await self.db.flush()
        await self.db.refresh(batch)

        await event_bus.publish("batch_payment.created", {
            "batch_id": str(batch.id),
            "batch_type": batch.batch_type,
            "payment_method": batch.payment_method,
        })

        logger.info("Created batch payment %s (%s)", batch.name, batch.id)
        return batch

    # ── Line Management ────────────────────────────────────────────────

    async def add_line(
        self,
        batch_id: uuid.UUID,
        data: BatchPaymentLineCreate,
    ) -> BatchPaymentLine:
        """Add a payment line to a draft batch."""
        batch = await self.batch_repo.get_with_lines_or_raise(batch_id)
        self._assert_draft(batch)

        line = BatchPaymentLine(
            batch_id=batch.id,
            partner_id=data.partner_id,
            invoice_id=data.invoice_id,
            amount=data.amount,
            currency_code=batch.currency_code,
            partner_bank_account=data.partner_bank_account,
            partner_bic=data.partner_bic,
            communication=data.communication,
            state="pending",
        )
        self.db.add(line)
        await self.db.flush()

        await self._recalculate_totals(batch)

        logger.info(
            "Added line to batch %s: partner=%s amount=%.2f",
            batch.name, data.partner_id, data.amount,
        )
        return line

    async def add_invoices_to_batch(
        self,
        batch_id: uuid.UUID,
        invoice_ids: list[uuid.UUID],
    ) -> list[BatchPaymentLine]:
        """Auto-create batch lines from selected invoices.

        Reads partner and amount_residual from each invoice (Move) to
        populate the line fields.
        """
        batch = await self.batch_repo.get_with_lines_or_raise(batch_id)
        self._assert_draft(batch)

        created_lines: list[BatchPaymentLine] = []

        for inv_id in invoice_ids:
            invoice: Move | None = await self.move_repo.get_by_id(inv_id)
            if invoice is None:
                raise NotFoundError("Invoice", str(inv_id))

            if invoice.amount_residual <= 0:
                logger.warning(
                    "Invoice %s has no residual amount, skipping", inv_id,
                )
                continue

            line = BatchPaymentLine(
                batch_id=batch.id,
                partner_id=invoice.partner_id,
                invoice_id=invoice.id,
                amount=invoice.amount_residual,
                currency_code=invoice.currency_code or batch.currency_code,
                communication=invoice.name or invoice.ref,
                state="pending",
            )
            self.db.add(line)
            created_lines.append(line)

        await self.db.flush()
        await self._recalculate_totals(batch)

        logger.info(
            "Added %d invoice lines to batch %s",
            len(created_lines), batch.name,
        )
        return created_lines

    async def remove_line(
        self,
        batch_id: uuid.UUID,
        line_id: uuid.UUID,
    ) -> None:
        """Remove a line from a draft batch."""
        batch = await self.batch_repo.get_with_lines_or_raise(batch_id)
        self._assert_draft(batch)

        line = await self.line_repo.get_by_id(line_id)
        if line is None or line.batch_id != batch.id:
            raise NotFoundError("BatchPaymentLine", str(line_id))

        await self.db.delete(line)
        await self.db.flush()
        await self._recalculate_totals(batch)

        logger.info("Removed line %s from batch %s", line_id, batch.name)

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def confirm_batch(
        self, batch_id: uuid.UUID,
    ) -> InvoiceBatchPayment:
        """Validate and confirm a draft batch."""
        batch = await self.batch_repo.get_with_lines_or_raise(batch_id)
        self._assert_draft(batch)

        if not batch.lines:
            raise BusinessRuleError("Cannot confirm an empty batch")

        # Validate SEPA-specific requirements
        if batch.payment_method in ("sepa_credit", "sepa_debit"):
            for line in batch.lines:
                if not line.partner_bank_account:
                    raise BusinessRuleError(
                        f"SEPA payment requires IBAN for all lines. "
                        f"Line for partner {line.partner_id} is missing IBAN."
                    )

        batch.state = "confirmed"
        if not batch.execution_date:
            batch.execution_date = date.today()

        await self.db.flush()

        await event_bus.publish("batch_payment.confirmed", {
            "batch_id": str(batch.id),
            "line_count": len(batch.lines),
            "total_amount": batch.total_amount,
        })

        logger.info("Confirmed batch %s with %d lines", batch.name, len(batch.lines))
        return batch

    async def execute_batch(
        self, batch_id: uuid.UUID,
    ) -> InvoiceBatchPayment:
        """Execute all payments in a confirmed batch.

        Creates individual Payment records via the accounting PaymentService,
        then marks the batch as sent.
        """
        batch = await self.batch_repo.get_with_lines_or_raise(batch_id)

        if batch.state != "confirmed":
            raise BusinessRuleError(
                f"Cannot execute batch in state '{batch.state}'. "
                f"Batch must be confirmed first."
            )

        pending_lines = [l for l in batch.lines if l.state == "pending"]
        if not pending_lines:
            raise BusinessRuleError("No pending lines to execute")

        # Determine payment_type and partner_type from batch_type
        if batch.batch_type == "outbound":
            payment_type = "outbound"
            partner_type = "supplier"
        else:
            payment_type = "inbound"
            partner_type = "customer"

        success_count = 0
        for line in pending_lines:
            try:
                payment_data = PaymentCreate(
                    payment_type=payment_type,
                    partner_type=partner_type,
                    amount=line.amount,
                    currency_code=line.currency_code,
                    date=batch.execution_date or date.today(),
                    partner_id=line.partner_id,
                    journal_id=batch.journal_id,
                    invoice_ids=[line.invoice_id] if line.invoice_id else None,
                    ref=line.communication,
                    memo=f"Batch payment: {batch.name}",
                )
                payment = await self.payment_service.create_payment(payment_data)
                await self.payment_service.confirm_payment(payment.id)

                line.payment_id = payment.id
                line.state = "paid"
                success_count += 1

            except Exception as exc:
                logger.error(
                    "Failed to execute line %s in batch %s: %s",
                    line.id, batch.name, exc,
                )
                line.state = "failed"
                line.error_message = str(exc)

        batch.state = "sent"
        await self.db.flush()

        await event_bus.publish("batch_payment.executed", {
            "batch_id": str(batch.id),
            "success_count": success_count,
            "failed_count": len(pending_lines) - success_count,
        })

        logger.info(
            "Executed batch %s: %d/%d succeeded",
            batch.name, success_count, len(pending_lines),
        )
        return batch

    async def cancel_batch(
        self, batch_id: uuid.UUID,
    ) -> InvoiceBatchPayment:
        """Cancel a batch payment."""
        batch = await self.batch_repo.get_with_lines_or_raise(batch_id)

        if batch.state in ("reconciled", "cancelled"):
            raise BusinessRuleError(
                f"Cannot cancel batch in state '{batch.state}'"
            )

        batch.state = "cancelled"

        # Mark all pending lines as failed
        for line in batch.lines:
            if line.state == "pending":
                line.state = "failed"
                line.error_message = "Batch cancelled"

        await self.db.flush()

        await event_bus.publish("batch_payment.cancelled", {
            "batch_id": str(batch.id),
        })

        logger.info("Cancelled batch %s", batch.name)
        return batch

    # ── Private Helpers ────────────────────────────────────────────────

    async def _recalculate_totals(
        self, batch: InvoiceBatchPayment,
    ) -> None:
        """Recalculate total_amount and payment_count from current lines."""
        lines = await self.line_repo.get_by_batch(batch.id)
        batch.total_amount = sum(line.amount for line in lines)
        batch.payment_count = len(lines)
        await self.db.flush()

    @staticmethod
    def _assert_draft(batch: InvoiceBatchPayment) -> None:
        """Raise if the batch is not in draft state."""
        if batch.state != "draft":
            raise BusinessRuleError(
                f"Batch must be in draft state to modify. "
                f"Current state: '{batch.state}'"
            )
