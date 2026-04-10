"""Pricelist and pricelist item models — the pricing engine.

Follows Odoo 19's rule-based pricelist architecture:
- A pricelist contains ordered rules (items)
- Rules match by scope: variant > product > category > global
- Rules compute price via: fixed, percentage, or formula
- Base price can chain to another pricelist (with recursion protection)
- Rules can be date-bounded and quantity-bounded
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
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


class Pricelist(UUIDMixin, TimestampMixin, Base):
    """A named set of pricing rules applied to customers or regions.

    Each tenant can have multiple pricelists (e.g. Retail, Wholesale, VIP,
    Export). Customers are assigned a default pricelist.
    """

    __tablename__ = "pricelists"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("16"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    currency_code: Mapped[str] = mapped_column(
        String(3), server_default=text("'USD'"),
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    items: Mapped[list["PricelistItem"]] = relationship(
        back_populates="pricelist",
        cascade="all, delete-orphan",
        order_by="PricelistItem.applied_on, PricelistItem.min_quantity.desc(), PricelistItem.sequence",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Pricelist name={self.name!r}>"


class PricelistItem(UUIDMixin, TimestampMixin, Base):
    """A single pricing rule within a pricelist.

    ``applied_on`` determines scope (most specific wins):
    - ``0_variant``: Matches a specific product variant
    - ``1_product``: Matches all variants of a product template
    - ``2_category``: Matches all products in a category (+ subcategories)
    - ``3_global``: Matches all products

    ``compute_price`` determines how the final price is calculated:
    - ``fixed``: Use ``fixed_price`` directly
    - ``percentage``: ``base_price * (1 - percent_price / 100)``
    - ``formula``: ``(base_price - base_price * discount/100) + surcharge``,
                   then round, then clamp within min/max margins

    ``base`` determines the starting price for percentage/formula:
    - ``list_price``: Product's list price
    - ``standard_price``: Product's cost price
    - ``pricelist``: Another pricelist's computed price (recursive)
    """

    __tablename__ = "pricelist_items"
    __table_args__ = (
        CheckConstraint(
            "date_start IS NULL OR date_end IS NULL OR date_start <= date_end",
            name="ck_pricelist_items_date_range",
        ),
        CheckConstraint(
            "price_min_margin IS NULL OR price_max_margin IS NULL OR price_min_margin <= price_max_margin",
            name="ck_pricelist_items_margin_range",
        ),
        Index("ix_pricelist_items_pricelist_id", "pricelist_id"),
    )

    pricelist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricelists.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))

    # ── Scope ─────────────────────────────────────────────────────────
    applied_on: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'3_global'"),
        doc="One of: 0_variant, 1_product, 2_category, 3_global.",
    )
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        nullable=True,
    )
    product_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_templates.id", ondelete="CASCADE"),
        nullable=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_categories.id", ondelete="CASCADE"),
        nullable=True,
    )

    # ── Pricing method ────────────────────────────────────────────────
    compute_price: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'fixed'"),
        doc="One of: fixed, percentage, formula.",
    )
    base: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'list_price'"),
        doc="One of: list_price, standard_price, pricelist.",
    )
    base_pricelist_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pricelists.id", ondelete="SET NULL"),
        nullable=True,
        doc="Used when base='pricelist'.",
    )

    # ── Price values ──────────────────────────────────────────────────
    fixed_price: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    percent_price: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Percentage discount (e.g. 10 = 10% off).",
    )
    price_discount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Formula mode: percentage discount.",
    )
    price_surcharge: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Formula mode: fixed amount added after discount.",
    )
    price_round: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Formula mode: round to nearest (e.g. 0.99, 5.0).",
    )
    price_min_margin: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        doc="Formula mode: minimum margin above cost.",
    )
    price_max_margin: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        doc="Formula mode: maximum margin above cost.",
    )

    # ── Conditions ────────────────────────────────────────────────────
    min_quantity: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Minimum quantity for this rule to apply.",
    )
    date_start: Mapped[datetime | None] = mapped_column(nullable=True)
    date_end: Mapped[datetime | None] = mapped_column(nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    pricelist: Mapped["Pricelist"] = relationship(
        back_populates="items",
        foreign_keys=[pricelist_id],
    )
    base_pricelist: Mapped["Pricelist | None"] = relationship(
        foreign_keys=[base_pricelist_id],
    )

    def __repr__(self) -> str:
        return f"<PricelistItem applied_on={self.applied_on} compute={self.compute_price}>"
