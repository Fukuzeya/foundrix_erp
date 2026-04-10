"""Journal Entry (account.move) and Journal Item (account.move.line) models.

The heart of double-entry accounting. Every financial transaction creates
a journal entry (move) with two or more journal items (lines) that must
balance: total debits = total credits.

Move types:
- entry: Generic journal entry
- out_invoice: Customer invoice
- out_refund: Customer credit note
- in_invoice: Vendor bill
- in_refund: Vendor refund
- out_receipt: Sales receipt
- in_receipt: Purchase receipt
"""

import uuid
from datetime import date, datetime

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


# Invoice types grouped by direction
OUTBOUND_TYPES = {"out_invoice", "out_refund", "out_receipt"}
INBOUND_TYPES = {"in_invoice", "in_refund", "in_receipt"}
INVOICE_TYPES = OUTBOUND_TYPES | INBOUND_TYPES

# Many-to-many: move line ↔ taxes applied
move_line_taxes = Table(
    "move_line_taxes",
    Base.metadata,
    mapped_column("move_line_id", ForeignKey("move_lines.id", ondelete="CASCADE"), primary_key=True),
    mapped_column("tax_id", ForeignKey("taxes.id", ondelete="CASCADE"), primary_key=True),
)


class Move(UUIDMixin, TimestampMixin, Base):
    """A journal entry — the fundamental accounting record.

    For invoices, this represents the full document (header + lines).
    For payments, this is the generated journal entry.
    """

    __tablename__ = "moves"
    __table_args__ = (
        Index("ix_moves_journal_id", "journal_id"),
        Index("ix_moves_state", "state"),
        Index("ix_moves_move_type", "move_type"),
        Index("ix_moves_partner_id", "partner_id"),
        Index("ix_moves_date", "date"),
        Index("ix_moves_payment_state", "payment_state"),
    )

    # ── Identification ────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(200), server_default=text("'/'"),
        doc="Sequence number assigned on posting (e.g. INV/2026/04/0001).",
    )
    ref: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        doc="External reference (vendor bill number, payment reference).",
    )

    # ── Type & State ──────────────────────────────────────────────────
    move_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'entry'"),
        doc="entry/out_invoice/out_refund/in_invoice/in_refund/out_receipt/in_receipt.",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'draft'"),
        doc="draft/posted/cancel.",
    )
    payment_state: Mapped[str] = mapped_column(
        String(20), server_default=text("'not_paid'"),
        doc="not_paid/partial/in_payment/paid/reversed.",
    )

    # ── Dates ─────────────────────────────────────────────────────────
    date: Mapped[date] = mapped_column(
        Date, server_default=text("CURRENT_DATE"),
        doc="Accounting date (date the entry is effective).",
    )
    invoice_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        doc="Date on the invoice document.",
    )
    invoice_date_due: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        doc="Due date for payment.",
    )

    # ── Relations ─────────────────────────────────────────────────────
    journal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"),
        nullable=True,
    )
    fiscal_position_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fiscal_positions.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_term_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_terms.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Currency ──────────────────────────────────────────────────────
    currency_code: Mapped[str] = mapped_column(
        String(3), server_default=text("'USD'"),
    )
    currency_rate: Mapped[float] = mapped_column(
        Float, server_default=text("1.0"),
        doc="Exchange rate at posting time.",
    )

    # ── Amounts (computed, stored) ────────────────────────────────────
    amount_untaxed: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    amount_tax: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    amount_total: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    amount_residual: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Remaining amount to be paid.",
    )
    amount_paid: Mapped[float] = mapped_column(Float, server_default=text("0.0"))

    # ── Auto-posting ──────────────────────────────────────────────────
    auto_post: Mapped[str] = mapped_column(
        String(20), server_default=text("'no'"),
        doc="no/at_date/monthly/quarterly/yearly.",
    )
    auto_post_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Audit trail ───────────────────────────────────────────────────
    inalterable_hash: Mapped[str | None] = mapped_column(
        String(256), nullable=True,
        doc="Tamper-proof hash chain for posted entries.",
    )
    secure_sequence_number: Mapped[int] = mapped_column(
        Integer, server_default=text("0"),
    )

    # ── Reversal tracking ─────────────────────────────────────────────
    reversed_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moves.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Narration ─────────────────────────────────────────────────────
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    journal: Mapped["Journal"] = relationship(lazy="selectin")
    lines: Mapped[list["MoveLine"]] = relationship(
        back_populates="move",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_invoice(self) -> bool:
        return self.move_type in INVOICE_TYPES

    @property
    def is_outbound(self) -> bool:
        return self.move_type in OUTBOUND_TYPES

    @property
    def is_inbound(self) -> bool:
        return self.move_type in INBOUND_TYPES

    @property
    def direction_sign(self) -> int:
        """+1 for outbound docs (customer invoice, vendor refund),
        -1 for inbound docs (vendor bill, customer refund)."""
        if self.move_type in ("out_invoice", "in_refund", "out_receipt"):
            return 1
        return -1

    def __repr__(self) -> str:
        return f"<Move name={self.name!r} type={self.move_type} state={self.state}>"


class MoveLine(UUIDMixin, TimestampMixin, Base):
    """A single line in a journal entry — one side of a double-entry transaction.

    Key invariants:
    - debit and credit cannot both be positive (debit * credit = 0)
    - balance = debit - credit
    - For multi-currency: amount_currency and balance must have same sign
    """

    __tablename__ = "move_lines"
    __table_args__ = (
        CheckConstraint(
            "debit >= 0 AND credit >= 0",
            name="ck_move_lines_positive_amounts",
        ),
        CheckConstraint(
            "debit * credit = 0",
            name="ck_move_lines_debit_credit_exclusive",
        ),
        Index("ix_move_lines_move_id", "move_id"),
        Index("ix_move_lines_account_id", "account_id"),
        Index("ix_move_lines_partner_id", "partner_id"),
        Index("ix_move_lines_date_maturity", "date_maturity"),
        Index(
            "ix_move_lines_unreconciled",
            "account_id", "partner_id",
            postgresql_where=text("reconciled IS NOT TRUE"),
        ),
    )

    move_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("moves.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Amounts ───────────────────────────────────────────────────────
    debit: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    credit: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    balance: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="debit - credit (positive = debit, negative = credit).",
    )
    amount_currency: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Amount in foreign currency.",
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), server_default=text("'USD'"),
    )

    # ── Invoice line fields ───────────────────────────────────────────
    display_type: Mapped[str] = mapped_column(
        String(30), server_default=text("'product'"),
        doc="product/tax/payment_term/rounding/line_section/line_note.",
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Line description.")
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    quantity: Mapped[float] = mapped_column(Float, server_default=text("1.0"))
    price_unit: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    discount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Discount percentage (0-100).",
    )
    price_subtotal: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Computed: quantity * price_unit * (1 - discount/100) before tax.",
    )
    price_total: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Computed: price_subtotal + taxes.",
    )

    # ── Tax ───────────────────────────────────────────────────────────
    tax_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("taxes.id", ondelete="SET NULL"),
        nullable=True,
        doc="The tax that generated this line (for tax lines).",
    )
    tax_base_amount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Base amount on which this tax was computed.",
    )
    tax_ids: Mapped[list["Tax"]] = relationship(
        secondary=move_line_taxes, lazy="selectin",
    )

    # ── Maturity ──────────────────────────────────────────────────────
    date_maturity: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        doc="Payment due date for receivable/payable lines.",
    )

    # ── Reconciliation ────────────────────────────────────────────────
    reconciled: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="True when amount_residual = 0.",
    )
    amount_residual: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Remaining amount to be reconciled.",
    )
    amount_residual_currency: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )
    full_reconcile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("full_reconciles.id", ondelete="SET NULL"),
        nullable=True,
    )
    matching_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        doc="Visual reconciliation identifier.",
    )

    # ── Analytic ──────────────────────────────────────────────────────
    analytic_distribution: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        doc="JSON mapping of analytic account IDs to percentages.",
    )

    # ── Sequence ──────────────────────────────────────────────────────
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))

    # ── Relationships ─────────────────────────────────────────────────
    move: Mapped["Move"] = relationship(back_populates="lines")
    account: Mapped["Account"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<MoveLine account={self.account_id} debit={self.debit} credit={self.credit}>"


# Forward references
from src.modules.accounting.models.journal import Journal  # noqa: E402
from src.modules.accounting.models.account import Account  # noqa: E402
from src.modules.accounting.models.tax import Tax  # noqa: E402
