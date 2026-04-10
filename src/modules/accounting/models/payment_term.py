"""Payment Terms and Fiscal Position models.

Payment terms define how an invoice amount is split across due dates.
Fiscal positions map taxes and accounts for different fiscal regimes.
"""

import uuid

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class PaymentTerm(UUIDMixin, TimestampMixin, Base):
    """Defines payment schedule (e.g. Net 30, 2/10 Net 30).

    Each term has lines that split the total amount into installments
    with different due dates.
    """

    __tablename__ = "payment_terms"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_on_invoice: Mapped[bool] = mapped_column(server_default=text("true"))
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))

    # ── Early payment discount ────────────────────────────────────────
    early_discount: Mapped[bool] = mapped_column(server_default=text("false"))
    discount_percentage: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )
    discount_days: Mapped[int] = mapped_column(
        Integer, server_default=text("0"),
    )

    lines: Mapped[list["PaymentTermLine"]] = relationship(
        back_populates="payment_term",
        cascade="all, delete-orphan",
        order_by="PaymentTermLine.sequence",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<PaymentTerm name={self.name!r}>"


class PaymentTermLine(UUIDMixin, Base):
    """A single installment within a payment term.

    value_type determines how amount is calculated:
    - percent: percentage of total
    - fixed: fixed amount
    - balance: remainder (must be last line)
    """

    __tablename__ = "payment_term_lines"

    payment_term_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_terms.id", ondelete="CASCADE"),
        nullable=False,
    )
    value_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'balance'"),
        doc="percent/fixed/balance.",
    )
    value_amount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Percentage or fixed amount.",
    )
    delay_type: Mapped[str] = mapped_column(
        String(30), server_default=text("'days_after_invoice'"),
        doc="days_after_invoice/days_after_end_of_month/days_after_end_of_next_month.",
    )
    nb_days: Mapped[int] = mapped_column(
        Integer, server_default=text("0"),
        doc="Number of days delay.",
    )
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))

    payment_term: Mapped["PaymentTerm"] = relationship(back_populates="lines")

    def __repr__(self) -> str:
        return f"<PaymentTermLine type={self.value_type} days={self.nb_days}>"


class FiscalPosition(UUIDMixin, TimestampMixin, Base):
    """Maps taxes and accounts for different fiscal regimes.

    Example: Intra-EU sales — maps domestic VAT to reverse-charge 0%.
    """

    __tablename__ = "fiscal_positions"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    auto_apply: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Automatically apply based on partner country.",
    )
    country_code: Mapped[str | None] = mapped_column(
        String(3), nullable=True,
        doc="Apply when partner is in this country.",
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    tax_mappings: Mapped[list["FiscalPositionTax"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
    )
    account_mappings: Mapped[list["FiscalPositionAccount"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<FiscalPosition name={self.name!r}>"


class FiscalPositionTax(UUIDMixin, Base):
    """Tax mapping within a fiscal position."""

    __tablename__ = "fiscal_position_taxes"

    fiscal_position_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    tax_src_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("taxes.id", ondelete="CASCADE"),
        nullable=False,
        doc="Source tax to replace.",
    )
    tax_dest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("taxes.id", ondelete="SET NULL"),
        nullable=True,
        doc="Replacement tax (null = exempt).",
    )


class FiscalPositionAccount(UUIDMixin, Base):
    """Account mapping within a fiscal position."""

    __tablename__ = "fiscal_position_accounts"

    fiscal_position_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_src_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_dest_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
