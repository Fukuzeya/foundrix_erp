"""Reconciliation models — matching payments to invoices.

Implements Odoo's three-level reconciliation:
1. PartialReconcile: links a debit line to a credit line with an amount
2. FullReconcile: promoted when all partials fully cover the amounts
3. ReconcileModel: rules for automatic matching (bank reconciliation)
"""

import uuid
from datetime import date

from sqlalchemy import (
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


class FullReconcile(UUIDMixin, TimestampMixin, Base):
    """Full reconciliation — all partial reconciliations are complete."""

    __tablename__ = "full_reconciles"

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    partials: Mapped[list["PartialReconcile"]] = relationship(
        back_populates="full_reconcile",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<FullReconcile name={self.name!r}>"


class PartialReconcile(UUIDMixin, TimestampMixin, Base):
    """A partial matching between a debit and credit journal item.

    When the sum of all partials for a set of lines equals the full
    amounts, a FullReconcile is automatically created.
    """

    __tablename__ = "partial_reconciles"
    __table_args__ = (
        Index("ix_partial_reconciles_debit_move_id", "debit_move_line_id"),
        Index("ix_partial_reconciles_credit_move_id", "credit_move_line_id"),
    )

    debit_move_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("move_lines.id", ondelete="CASCADE"),
        nullable=False,
    )
    credit_move_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("move_lines.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(
        Float, nullable=False,
        doc="Amount reconciled in company currency (always positive).",
    )
    debit_amount_currency: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )
    credit_amount_currency: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )
    full_reconcile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("full_reconciles.id", ondelete="SET NULL"),
        nullable=True,
    )
    exchange_move_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moves.id", ondelete="SET NULL"),
        nullable=True,
        doc="Auto-generated exchange difference entry.",
    )

    full_reconcile: Mapped["FullReconcile | None"] = relationship(
        back_populates="partials",
    )

    def __repr__(self) -> str:
        return f"<PartialReconcile amount={self.amount}>"


class ReconcileModel(UUIDMixin, TimestampMixin, Base):
    """Rules for automatic bank statement reconciliation.

    When importing bank statements, these rules try to match
    transactions to invoices/bills automatically.
    """

    __tablename__ = "reconcile_models"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    rule_type: Mapped[str] = mapped_column(
        String(30), server_default=text("'writeoff_button'"),
        doc="writeoff_button/writeoff_suggestion/invoice_matching.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    auto_reconcile: Mapped[bool] = mapped_column(server_default=text("false"))

    # ── Matching conditions ───────────────────────────────────────────
    match_label: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        doc="contains/not_contains/match_regex.",
    )
    match_label_param: Mapped[str | None] = mapped_column(String(500), nullable=True)
    match_amount: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        doc="lower/greater/between.",
    )
    match_amount_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_amount_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_partner: Mapped[bool] = mapped_column(server_default=text("false"))

    # ── Write-off ─────────────────────────────────────────────────────
    lines: Mapped[list["ReconcileModelLine"]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ReconcileModel name={self.name!r} type={self.rule_type}>"


class ReconcileModelLine(UUIDMixin, Base):
    """A write-off line template for a reconcile model."""

    __tablename__ = "reconcile_model_lines"

    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconcile_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'percentage'"),
        doc="fixed/percentage/percentage_st_line/regex.",
    )
    amount_string: Mapped[str] = mapped_column(
        String(100), server_default=text("'100'"),
    )
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))

    model: Mapped["ReconcileModel"] = relationship(back_populates="lines")

    def __repr__(self) -> str:
        return f"<ReconcileModelLine account={self.account_id}>"
