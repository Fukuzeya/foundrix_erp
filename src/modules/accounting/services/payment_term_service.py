"""Payment term and fiscal position service.

Handles:
- Payment term CRUD with lines management
- Due date computation from payment term lines (critical for invoicing)
- Fiscal position CRUD with tax and account mappings
- Fiscal position account mapping for invoice line accounts
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from calendar import monthrange
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from src.modules.accounting.models.payment_term import (
    PaymentTerm,
    PaymentTermLine,
    FiscalPosition,
    FiscalPositionTax,
    FiscalPositionAccount,
)
from src.modules.accounting.repositories.payment_term_repo import (
    PaymentTermRepository,
    FiscalPositionRepository,
)
from src.modules.accounting.schemas.payment_term import (
    PaymentTermCreate,
    PaymentTermUpdate,
    FiscalPositionCreate,
    FiscalPositionUpdate,
)

logger = logging.getLogger(__name__)


@dataclass
class DueDateInstallment:
    """A single installment computed from payment term lines."""
    date: date
    amount: float
    percentage: float


class PaymentTermService:
    """Manages payment terms and computes due dates."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PaymentTermRepository(db)
        self.fp_repo = FiscalPositionRepository(db)

    # ── Payment Terms ────────────────────────────────────────────────

    async def list_payment_terms(self) -> list[PaymentTerm]:
        """List all active payment terms."""
        return await self.repo.list_active()

    async def create_payment_term(self, data: PaymentTermCreate) -> PaymentTerm:
        """Create a payment term with its lines."""
        # Validate lines add up correctly
        if data.lines:
            self._validate_term_lines(data.lines)

        term_data = data.model_dump(exclude={"lines"})
        term = await self.repo.create(**term_data)

        if data.lines:
            for line_data in data.lines:
                line = PaymentTermLine(
                    payment_term_id=term.id,
                    **line_data.model_dump(),
                )
                self.db.add(line)

        await self.db.flush()
        await self.db.refresh(term)
        return term

    async def get_payment_term(self, term_id: uuid.UUID) -> PaymentTerm:
        """Get a payment term by ID or raise NotFoundError."""
        return await self.repo.get_by_id_or_raise(term_id, "PaymentTerm")

    async def update_payment_term(self, term_id: uuid.UUID, data: PaymentTermUpdate) -> PaymentTerm:
        """Update a payment term."""
        term = await self.repo.get_by_id_or_raise(term_id, "PaymentTerm")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(term, key, value)

        await self.db.flush()
        await self.db.refresh(term)
        return term

    def compute_due_dates(
        self, payment_term: PaymentTerm, total_amount: float, invoice_date: date,
    ) -> list[DueDateInstallment]:
        """Compute installment due dates and amounts from payment term lines.

        This is the core computation that determines when each portion of an
        invoice is due, based on the payment term's line configuration.

        Follows Odoo's logic:
        - 'percent' lines: percentage of total
        - 'fixed' lines: fixed amount
        - 'balance' line: remainder (must be exactly one)
        """
        if not payment_term.lines:
            # No lines = immediate payment
            return [DueDateInstallment(date=invoice_date, amount=total_amount, percentage=100.0)]

        lines = sorted(payment_term.lines, key=lambda l: l.sequence)
        installments: list[DueDateInstallment] = []
        remaining = total_amount

        for line in lines:
            due_date = self._compute_line_due_date(line, invoice_date)

            if line.value_type == "percent":
                amount = round(total_amount * line.value_amount / 100.0, 2)
                percentage = line.value_amount
            elif line.value_type == "fixed":
                amount = min(line.value_amount, remaining)
                percentage = round(amount / total_amount * 100, 2) if total_amount else 0
            else:  # balance
                amount = round(remaining, 2)
                percentage = round(amount / total_amount * 100, 2) if total_amount else 0

            remaining -= amount
            installments.append(DueDateInstallment(
                date=due_date, amount=amount, percentage=percentage,
            ))

        return installments

    def _compute_line_due_date(self, line: PaymentTermLine, invoice_date: date) -> date:
        """Compute the due date for a single payment term line."""
        if line.delay_type == "days_after_invoice":
            from datetime import timedelta
            return invoice_date + timedelta(days=line.nb_days)

        elif line.delay_type == "days_after_end_of_month":
            from datetime import timedelta
            # Go to end of current month
            last_day = monthrange(invoice_date.year, invoice_date.month)[1]
            end_of_month = invoice_date.replace(day=last_day)
            return end_of_month + timedelta(days=line.nb_days)

        elif line.delay_type == "days_after_end_of_next_month":
            from datetime import timedelta
            # Go to end of next month
            if invoice_date.month == 12:
                next_month = invoice_date.replace(year=invoice_date.year + 1, month=1, day=1)
            else:
                next_month = invoice_date.replace(month=invoice_date.month + 1, day=1)
            last_day = monthrange(next_month.year, next_month.month)[1]
            end_of_next_month = next_month.replace(day=last_day)
            return end_of_next_month + timedelta(days=line.nb_days)

        return invoice_date

    def _validate_term_lines(self, lines) -> None:
        """Validate that payment term lines are consistent."""
        balance_count = sum(1 for l in lines if l.value_type == "balance")
        if balance_count > 1:
            raise ValidationError("Payment term can have at most one 'balance' line")

        percent_total = sum(l.value_amount for l in lines if l.value_type == "percent")
        if percent_total > 100:
            raise ValidationError(f"Percent lines total ({percent_total}%) exceeds 100%")

    # ── Fiscal Positions ─────────────────────────────────────────────

    async def list_fiscal_positions(self) -> list[FiscalPosition]:
        """List all active fiscal positions."""
        return await self.fp_repo.list_active()

    async def create_fiscal_position(self, data: FiscalPositionCreate) -> FiscalPosition:
        """Create a fiscal position with tax and account mappings."""
        fp_data = data.model_dump(exclude={"tax_mappings", "account_mappings"})
        fp = await self.fp_repo.create(**fp_data)

        if data.tax_mappings:
            for mapping in data.tax_mappings:
                tax_map = FiscalPositionTax(
                    fiscal_position_id=fp.id,
                    tax_src_id=mapping.tax_src_id,
                    tax_dest_id=mapping.tax_dest_id,
                )
                self.db.add(tax_map)

        if data.account_mappings:
            for mapping in data.account_mappings:
                acct_map = FiscalPositionAccount(
                    fiscal_position_id=fp.id,
                    account_src_id=mapping.account_src_id,
                    account_dest_id=mapping.account_dest_id,
                )
                self.db.add(acct_map)

        await self.db.flush()
        await self.db.refresh(fp)
        return fp

    async def get_fiscal_position(self, fp_id: uuid.UUID) -> FiscalPosition:
        """Get a fiscal position by ID or raise NotFoundError."""
        return await self.fp_repo.get_by_id_or_raise(fp_id, "FiscalPosition")

    async def update_fiscal_position(self, fp_id: uuid.UUID, data: FiscalPositionUpdate) -> FiscalPosition:
        """Update a fiscal position."""
        fp = await self.fp_repo.get_by_id_or_raise(fp_id, "FiscalPosition")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(fp, key, value)

        await self.db.flush()
        await self.db.refresh(fp)
        return fp

    async def map_account(self, fiscal_position_id: uuid.UUID, account_id: uuid.UUID) -> uuid.UUID:
        """Apply fiscal position account mapping: replace source account with destination."""
        fp = await self.fp_repo.get_by_id(fiscal_position_id)
        if not fp:
            return account_id

        for mapping in fp.account_mappings:
            if mapping.account_src_id == account_id:
                return mapping.account_dest_id

        return account_id
