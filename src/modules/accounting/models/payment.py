"""Payment model — records payments and generates journal entries.

Payments link to invoices and create reconciliation entries.
Supports inbound (customer payments) and outbound (vendor payments),
batch payments, and internal transfers.
"""

import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


# Many-to-many: payment ↔ invoices being paid
payment_invoices = Table(
    "payment_invoices",
    Base.metadata,
    mapped_column("payment_id", ForeignKey("payments.id", ondelete="CASCADE"), primary_key=True),
    mapped_column("move_id", ForeignKey("moves.id", ondelete="CASCADE"), primary_key=True),
)


class PaymentMethod(UUIDMixin, Base):
    """A method of payment (e.g. Manual, Bank Transfer, Check, SEPA)."""

    __tablename__ = "payment_methods"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    payment_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="One of: inbound, outbound.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    def __repr__(self) -> str:
        return f"<PaymentMethod code={self.code!r}>"


class Payment(UUIDMixin, TimestampMixin, Base):
    """A payment record.

    States: draft → posted → reconciled
                  → cancelled
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payments_positive_amount"),
        Index("ix_payments_state", "state"),
        Index("ix_payments_partner_id", "partner_id"),
        Index("ix_payments_date", "date"),
    )

    # ── Type & State ──────────────────────────────────────────────────
    payment_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="inbound (receive money) or outbound (send money).",
    )
    partner_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="customer or supplier.",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'draft'"),
        doc="draft/posted/reconciled/cancelled.",
    )

    # ── Amounts ───────────────────────────────────────────────────────
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))

    # ── Date ──────────────────────────────────────────────────────────
    date: Mapped[date] = mapped_column(
        Date, server_default=text("CURRENT_DATE"),
    )

    # ── Relations ─────────────────────────────────────────────────────
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"),
        nullable=True,
    )
    journal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="SET NULL"),
        nullable=True,
    )
    destination_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        doc="Receivable or payable account (auto-computed from partner_type).",
    )

    # ── Generated journal entry ───────────────────────────────────────
    move_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moves.id", ondelete="SET NULL"),
        nullable=True,
        doc="The journal entry generated when this payment is posted.",
    )

    # ── Batch & Transfer ──────────────────────────────────────────────
    batch_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batch_payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_internal_transfer: Mapped[bool] = mapped_column(
        server_default=text("false"),
    )

    # ── Reconciliation status ─────────────────────────────────────────
    is_reconciled: Mapped[bool] = mapped_column(server_default=text("false"))
    is_matched: Mapped[bool] = mapped_column(server_default=text("false"))

    # ── Reference ─────────────────────────────────────────────────────
    ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    journal: Mapped["Journal"] = relationship(lazy="selectin")
    invoice_ids: Mapped[list["Move"]] = relationship(
        secondary=payment_invoices, lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Payment type={self.payment_type} amount={self.amount} state={self.state}>"


class BatchPayment(UUIDMixin, TimestampMixin, Base):
    """Group multiple payments for batch processing (checks, wire transfers)."""

    __tablename__ = "batch_payments"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    batch_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="inbound or outbound.",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'draft'"),
        doc="draft/sent/reconciled.",
    )
    date: Mapped[date] = mapped_column(Date, server_default=text("CURRENT_DATE"))
    journal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"),
        nullable=False,
    )

    payments: Mapped[list["Payment"]] = relationship(
        foreign_keys=[Payment.batch_payment_id],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<BatchPayment name={self.name!r} state={self.state}>"


# Forward references
from src.modules.accounting.models.journal import Journal  # noqa: E402
from src.modules.accounting.models.move import Move  # noqa: E402
