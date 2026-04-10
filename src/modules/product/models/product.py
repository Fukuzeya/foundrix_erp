"""Product Template and Product Variant models.

Follows Odoo's two-level product architecture:
- ProductTemplate: master record with shared data (name, description, category, UoM, base price)
- ProductVariant: concrete SKU with variant-specific data (barcode, cost, attribute values)

A template with no variant-creating attributes has exactly one "implicit" variant.
A template with attributes has N variants = Cartesian product of attribute values.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


# ── Product Tags ──────────────────────────────────────────────────────

class ProductTag(UUIDMixin, Base):
    """Tags for organizing and filtering products."""

    __tablename__ = "product_tags"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    color: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    def __repr__(self) -> str:
        return f"<ProductTag name={self.name!r}>"


# Many-to-many: template ↔ tags
product_template_tags = Table(
    "product_template_tags",
    Base.metadata,
    mapped_column("template_id", ForeignKey("product_templates.id", ondelete="CASCADE"), primary_key=True),
    mapped_column("tag_id", ForeignKey("product_tags.id", ondelete="CASCADE"), primary_key=True),
)


# Many-to-many: variant ↔ template attribute values
variant_attribute_values = Table(
    "product_variant_attribute_values",
    Base.metadata,
    mapped_column("variant_id", ForeignKey("product_variants.id", ondelete="CASCADE"), primary_key=True),
    mapped_column("ptav_id", ForeignKey("product_template_attribute_values.id", ondelete="CASCADE"), primary_key=True),
)


# ── Product Template ─────────────────────────────────────────────────

class ProductTemplate(UUIDMixin, TimestampMixin, Base):
    """Master product record holding shared data across all variants.

    ``product_type`` determines behaviour in inventory/accounting:
    - ``goods``: Physical product (stockable, affects inventory)
    - ``service``: Non-physical service (no stock impact)
    - ``consumable``: Physical but not tracked in inventory
    """

    __tablename__ = "product_templates"
    __table_args__ = (
        Index("ix_product_templates_categ_id", "category_id"),
        Index("ix_product_templates_active", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    product_type: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'goods'"),
        doc="One of: goods, service, consumable.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    is_favorite: Mapped[bool] = mapped_column(server_default=text("false"))

    # ── Descriptions ──────────────────────────────────────────────────
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_sale: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Description shown on sales documents.",
    )
    description_purchase: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Description shown on purchase documents.",
    )

    # ── Pricing ───────────────────────────────────────────────────────
    list_price: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Base sales price before attribute extras.",
    )
    standard_price: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Cost price (used for COGS, margin analysis).",
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), server_default=text("'USD'"),
    )

    # ── Classification ────────────────────────────────────────────────
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    sale_ok: Mapped[bool] = mapped_column(
        server_default=text("true"), doc="Can be sold.",
    )
    purchase_ok: Mapped[bool] = mapped_column(
        server_default=text("true"), doc="Can be purchased.",
    )

    # ── Unit of Measure ───────────────────────────────────────────────
    uom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uoms.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Default unit of measure for this product.",
    )
    uom_purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("uoms.id", ondelete="SET NULL"),
        nullable=True,
        doc="Unit of measure for purchasing (if different from sales UoM).",
    )

    # ── Physical ──────────────────────────────────────────────────────
    weight: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    volume: Mapped[float] = mapped_column(Float, server_default=text("0.0"))

    # ── Defaults from single variant (for templates with one variant) ──
    default_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="Internal reference (synced from single variant).",
    )
    barcode: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="Barcode (synced from single variant).",
    )

    # ── Internal notes ────────────────────────────────────────────────
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    category: Mapped["ProductCategory | None"] = relationship(lazy="selectin")
    uom: Mapped["Uom"] = relationship(foreign_keys=[uom_id], lazy="selectin")
    uom_purchase: Mapped["Uom | None"] = relationship(
        foreign_keys=[uom_purchase_id], lazy="selectin",
    )
    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    attribute_lines: Mapped[list["ProductTemplateAttributeLine"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProductTemplateAttributeLine.sequence",
    )
    tags: Mapped[list["ProductTag"]] = relationship(
        secondary=product_template_tags,
        lazy="selectin",
    )

    @property
    def has_variants(self) -> bool:
        """True if this template has multiple active variants."""
        return len([v for v in self.variants if v.is_active]) > 1

    @property
    def variant_count(self) -> int:
        return len([v for v in self.variants if v.is_active])

    def __repr__(self) -> str:
        return f"<ProductTemplate name={self.name!r} type={self.product_type}>"


# ── Product Variant ───────────────────────────────────────────────────

class ProductVariant(UUIDMixin, TimestampMixin, Base):
    """A concrete, sellable/purchasable product SKU.

    Each variant belongs to exactly one template. The variant holds:
    - Its specific attribute value combination
    - Its own barcode, internal reference, cost
    - Inventory quantities (qty_available, virtual_available)

    ``combination_indices`` is a stored hash of the attribute value IDs,
    used for fast lookups and uniqueness enforcement.
    """

    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "combination_indices",
            name="uq_product_variants_tmpl_combination",
        ),
        Index("ix_product_variants_template_id", "template_id"),
        Index("ix_product_variants_barcode", "barcode"),
        Index("ix_product_variants_default_code", "default_code"),
        Index("ix_product_variants_active", "is_active"),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    # ── Identification ────────────────────────────────────────────────
    default_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="Internal reference / SKU.",
    )
    barcode: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )

    # ── Variant-specific pricing ──────────────────────────────────────
    standard_price: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Variant-specific cost price.",
    )
    price_extra: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Computed sum of attribute price extras.",
    )
    lst_price: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Computed: template list_price + price_extra.",
    )

    # ── Physical ──────────────────────────────────────────────────────
    weight: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    volume: Mapped[float] = mapped_column(Float, server_default=text("0.0"))

    # ── Attribute combination hash ────────────────────────────────────
    combination_indices: Mapped[str] = mapped_column(
        String(500),
        server_default=text("''"),
        doc="Sorted, comma-joined PTAV IDs for uniqueness and lookup.",
    )

    # ── Relationships ─────────────────────────────────────────────────
    template: Mapped["ProductTemplate"] = relationship(back_populates="variants")
    attribute_values: Mapped[list["ProductTemplateAttributeValue"]] = relationship(
        secondary=variant_attribute_values,
        lazy="selectin",
    )

    @property
    def display_name(self) -> str:
        """Compute display name: 'Template Name (Color: Red, Size: M)'."""
        base = self.template.name if self.template else ""
        if not self.attribute_values:
            return base

        attrs = ", ".join(
            f"{ptav.attribute_value.attribute.name}: {ptav.attribute_value.name}"
            for ptav in sorted(self.attribute_values, key=lambda v: v.attribute_line.sequence)
            if ptav.attribute_value and ptav.attribute_value.attribute
        )
        return f"{base} ({attrs})" if attrs else base

    def __repr__(self) -> str:
        return f"<ProductVariant template={self.template_id} code={self.default_code!r}>"


# Forward references for type checking
from src.modules.product.models.category import ProductCategory  # noqa: E402
from src.modules.product.models.uom import Uom  # noqa: E402
from src.modules.product.models.attribute import (  # noqa: E402
    ProductTemplateAttributeLine,
    ProductTemplateAttributeValue,
)
