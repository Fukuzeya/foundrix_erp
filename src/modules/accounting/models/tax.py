"""Tax model — the tax computation engine.

Supports all standard tax types:
- Fixed: absolute amount per unit
- Percentage: percentage of base
- Division: percentage included in price (VAT-inclusive)
- Group: container for child taxes

Handles:
- Price-included vs price-excluded taxes
- Tax-on-tax (include_base_amount)
- Repartition lines for account/tag mapping
- Cash basis taxes (recognized on payment)
- Early payment discounts
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
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


# Many-to-many: group taxes contain child taxes
tax_children = Table(
    "tax_children",
    Base.metadata,
    mapped_column("parent_tax_id", ForeignKey("taxes.id", ondelete="CASCADE"), primary_key=True),
    mapped_column("child_tax_id", ForeignKey("taxes.id", ondelete="CASCADE"), primary_key=True),
)


class Tax(UUIDMixin, TimestampMixin, Base):
    """A tax definition.

    The ``amount_type`` determines computation:
    - ``percent``: tax = base × amount / 100
    - ``fixed``: tax = quantity × amount
    - ``division``: tax = base − base / (1 + amount / 100) (price-included)
    - ``group``: delegates to ``children_tax_ids``
    """

    __tablename__ = "taxes"
    __table_args__ = (
        Index("ix_taxes_type_tax_use", "type_tax_use"),
        Index("ix_taxes_active", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type_tax_use: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="One of: sale, purchase, none.",
    )
    amount_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'percent'"),
        doc="One of: percent, fixed, division, group.",
    )
    amount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Tax rate (e.g. 15.0 for 15% VAT).",
    )
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Price inclusion ───────────────────────────────────────────────
    price_include: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Tax included in the displayed price.",
    )

    # ── Tax-on-tax ────────────────────────────────────────────────────
    include_base_amount: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Add this tax to the base for subsequent taxes.",
    )
    is_base_affected: Mapped[bool] = mapped_column(
        server_default=text("true"),
        doc="Whether prior include_base_amount taxes affect this tax's base.",
    )

    # ── Cash basis ────────────────────────────────────────────────────
    tax_exigibility: Mapped[str] = mapped_column(
        String(20), server_default=text("'on_invoice'"),
        doc="One of: on_invoice, on_payment.",
    )
    cash_basis_transition_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Display ───────────────────────────────────────────────────────
    invoice_label: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        doc="Label shown on invoices (defaults to name).",
    )

    # ── Group taxes ───────────────────────────────────────────────────
    children_tax_ids: Mapped[list["Tax"]] = relationship(
        secondary=tax_children,
        primaryjoin="Tax.id == tax_children.c.parent_tax_id",
        secondaryjoin="Tax.id == tax_children.c.child_tax_id",
        lazy="selectin",
    )

    # ── Repartition ───────────────────────────────────────────────────
    invoice_repartition_lines: Mapped[list["TaxRepartitionLine"]] = relationship(
        back_populates="tax",
        primaryjoin="and_(TaxRepartitionLine.tax_id == Tax.id, TaxRepartitionLine.document_type == 'invoice')",
        cascade="all, delete-orphan",
        lazy="selectin",
        viewonly=True,
    )
    refund_repartition_lines: Mapped[list["TaxRepartitionLine"]] = relationship(
        back_populates="tax",
        primaryjoin="and_(TaxRepartitionLine.tax_id == Tax.id, TaxRepartitionLine.document_type == 'refund')",
        cascade="all, delete-orphan",
        lazy="selectin",
        viewonly=True,
    )

    def compute_amount(
        self, base: float, quantity: float = 1.0, price_unit: float | None = None,
    ) -> float:
        """Compute the tax amount for a given base.

        For fixed taxes, ``quantity`` and ``price_unit`` determine the sign.
        For percentage/division, only ``base`` matters.
        """
        if self.amount_type == "fixed":
            sign = -1.0 if (price_unit or base) < 0 else 1.0
            return sign * abs(quantity) * self.amount

        elif self.amount_type == "percent":
            return base * self.amount / 100.0

        elif self.amount_type == "division":
            if self.amount == 0:
                return 0.0
            return base - base / (1.0 + self.amount / 100.0)

        elif self.amount_type == "group":
            # Group taxes delegate to children
            total = 0.0
            current_base = base
            for child in sorted(self.children_tax_ids, key=lambda t: t.sequence):
                child_amount = child.compute_amount(current_base, quantity, price_unit)
                total += child_amount
                if child.include_base_amount:
                    current_base += child_amount
            return total

        return 0.0

    def __repr__(self) -> str:
        return f"<Tax name={self.name!r} type={self.amount_type} amount={self.amount}>"


class TaxRepartitionLine(UUIDMixin, Base):
    """Defines how a tax amount is distributed across accounts and tags.

    Each tax has invoice + refund repartition lines:
    - Base line (repartition_type='base'): tags the base amount
    - Tax line (repartition_type='tax'): posts the tax amount to an account
    """

    __tablename__ = "tax_repartition_lines"
    __table_args__ = (
        Index("ix_tax_repartition_lines_tax_id", "tax_id"),
    )

    tax_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("taxes.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="One of: invoice, refund.",
    )
    repartition_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="One of: base, tax.",
    )
    factor_percent: Mapped[float] = mapped_column(
        Float, server_default=text("100.0"),
        doc="Percentage of the tax allocated to this line.",
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        doc="Account to post to (null for base lines).",
    )
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    tax: Mapped["Tax"] = relationship(
        back_populates=None, foreign_keys=[tax_id],
    )

    def __repr__(self) -> str:
        return f"<TaxRepartitionLine tax={self.tax_id} type={self.repartition_type} factor={self.factor_percent}>"
