"""Bank Statement models — import and reconciliation of bank feeds.

Supports importing statements in multiple formats (OFX, CSV, CAMT.053)
and automatic reconciliation with invoices/payments.
"""

import uuid
from datetime import date

from sqlalchemy import (
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class BankStatement(UUIDMixin, TimestampMixin, Base):
    """A bank statement imported from a bank feed or file."""

    __tablename__ = "bank_statements"
    __table_args__ = (
        Index("ix_bank_statements_journal_id", "journal_id"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    journal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    balance_start: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    balance_end_real: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    balance_end: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Computed: balance_start + sum(line amounts).",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'open'"),
        doc="open/confirm.",
    )
    import_format: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        doc="ofx/csv/camt053/coda/qif/manual.",
    )

    lines: Mapped[list["BankStatementLine"]] = relationship(
        back_populates="statement",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<BankStatement name={self.name!r} state={self.state}>"


class BankStatementLine(UUIDMixin, TimestampMixin, Base):
    """A single transaction within a bank statement."""

    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        Index("ix_bank_statement_lines_statement_id", "statement_id"),
    )

    statement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False, doc="Transaction label.")
    ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"),
        nullable=True,
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))

    # ── Reconciliation ────────────────────────────────────────────────
    is_reconciled: Mapped[bool] = mapped_column(server_default=text("false"))
    move_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moves.id", ondelete="SET NULL"),
        nullable=True,
        doc="Journal entry created for reconciliation.",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    statement: Mapped["BankStatement"] = relationship(back_populates="lines")

    def __repr__(self) -> str:
        return f"<BankStatementLine name={self.name!r} amount={self.amount}>"
