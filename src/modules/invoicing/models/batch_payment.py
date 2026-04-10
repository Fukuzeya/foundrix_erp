"""Enhanced batch payment models for the invoicing module.

Supports batch processing of payments with SEPA, check, wire, and manual
methods. Each batch contains payment lines that reference partners and
invoices, and can generate SEPA XML files or check PDFs.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import (
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class BatchType(str, enum.Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class PaymentMethodType(str, enum.Enum):
    SEPA_CREDIT = "sepa_credit"
    SEPA_DEBIT = "sepa_debit"
    CHECK = "check"
    WIRE = "wire"
    MANUAL = "manual"


class InvoiceBatchPayment(Base, UUIDMixin, TimestampMixin):
    """Enhanced batch payment for invoicing — groups payment lines for
    batch execution via SEPA, check, wire, or manual methods.

    States: draft -> confirmed -> sent -> reconciled
                               -> cancelled
    """

    __tablename__ = "invoice_batch_payments"
    __table_args__ = (
        Index("ix_invoice_batch_payments_state", "state"),
        Index("ix_invoice_batch_payments_journal_id", "journal_id"),
        Index("ix_invoice_batch_payments_execution_date", "execution_date"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    batch_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="outbound (pay vendors) or inbound (collect from customers).",
    )
    payment_method: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="sepa_credit, sepa_debit, check, wire, or manual.",
    )
    journal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), server_default=text("'USD'"),
    )
    total_amount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )
    payment_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"),
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'draft'"),
        doc="draft/confirmed/sent/reconciled/cancelled.",
    )
    execution_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
    )
    generated_file: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
        doc="SEPA XML or check PDF binary content.",
    )
    generated_filename: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────
    lines: Mapped[list["BatchPaymentLine"]] = relationship(
        back_populates="batch",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<InvoiceBatchPayment name={self.name!r} "
            f"method={self.payment_method} state={self.state}>"
        )


class BatchPaymentLine(Base, UUIDMixin, TimestampMixin):
    """A single payment line within an invoice batch payment."""

    __tablename__ = "batch_payment_lines"
    __table_args__ = (
        Index("ix_batch_payment_lines_batch_id", "batch_id"),
        Index("ix_batch_payment_lines_partner_id", "partner_id"),
        Index("ix_batch_payment_lines_state", "state"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoice_batch_payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        doc="Reference to the invoice (moves) being paid.",
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(3), server_default=text("'USD'"),
    )
    partner_bank_account: Mapped[str | None] = mapped_column(
        String(34), nullable=True,
        doc="IBAN for SEPA payments.",
    )
    partner_bic: Mapped[str | None] = mapped_column(
        String(11), nullable=True,
        doc="BIC/SWIFT code for SEPA payments.",
    )
    communication: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        doc="Payment reference / remittance information.",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'pending'"),
        doc="pending/paid/failed.",
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        doc="Links to the Payment record created after execution.",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    # ── Relationships ──────────────────────────────────────────────────
    batch: Mapped["InvoiceBatchPayment"] = relationship(
        back_populates="lines",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<BatchPaymentLine partner={self.partner_id} "
            f"amount={self.amount} state={self.state}>"
        )
