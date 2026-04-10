"""Product attribute models — drives the variant matrix.

Four-layer attribute architecture (following Odoo 19):

1. ProductAttribute      — defines the dimension (e.g. Color, Size)
2. ProductAttributeValue  — global values for that dimension (Red, Blue, S, M, L)
3. ProductTemplateAttributeLine — links an attribute to a template with selected values
4. ProductTemplateAttributeValue — per-template value customization (price extra, exclusions)

The Cartesian product of all attribute lines generates the variant matrix.
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


class ProductAttribute(UUIDMixin, TimestampMixin, Base):
    """A product dimension like Color, Size, Material.

    ``create_variant`` controls how this attribute generates variants:
    - ``always``: Variants are pre-created for all combinations
    - ``dynamic``: Variants created on-demand (e.g. when added to cart)
    - ``no_variant``: Attribute recorded at order-line level, no variants created
    """

    __tablename__ = "product_attributes"
    __table_args__ = (
        CheckConstraint(
            "NOT (display_type = 'multi' AND create_variant != 'no_variant')",
            name="ck_product_attributes_multi_no_variant",
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    display_type: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'radio'"),
        doc="One of: radio, pills, select, color, multi.",
    )
    create_variant: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'always'"),
        doc="One of: always, dynamic, no_variant.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    values: Mapped[list["ProductAttributeValue"]] = relationship(
        back_populates="attribute",
        cascade="all, delete-orphan",
        order_by="ProductAttributeValue.sequence",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ProductAttribute name={self.name!r} create_variant={self.create_variant}>"


class ProductAttributeValue(UUIDMixin, TimestampMixin, Base):
    """A concrete value for an attribute (e.g. 'Red' for Color, 'XL' for Size).

    Global values that can be reused across multiple product templates.
    """

    __tablename__ = "product_attribute_values"
    __table_args__ = (
        UniqueConstraint("attribute_id", "name", name="uq_product_attribute_values_attr_name"),
        Index("ix_product_attribute_values_attribute_id", "attribute_id"),
    )

    attribute_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_attributes.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    html_color: Mapped[str | None] = mapped_column(
        String(10), nullable=True, doc="Hex color for 'color' display type.",
    )
    is_custom: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Allow free-text custom value from customer.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    attribute: Mapped["ProductAttribute"] = relationship(back_populates="values")

    def __repr__(self) -> str:
        return f"<ProductAttributeValue name={self.name!r}>"


# Many-to-many: which attribute values are selected for a template attribute line
template_attribute_line_values = Table(
    "product_tmpl_attr_line_values",
    Base.metadata,
    mapped_column("line_id", ForeignKey("product_template_attribute_lines.id", ondelete="CASCADE"), primary_key=True),
    mapped_column("value_id", ForeignKey("product_attribute_values.id", ondelete="CASCADE"), primary_key=True),
)


class ProductTemplateAttributeLine(UUIDMixin, TimestampMixin, Base):
    """Links an attribute to a product template with the subset of selected values.

    For example: Template "T-Shirt" has attribute line for "Size" with values [S, M, L, XL].
    Another line for "Color" with values [Red, Blue, Green].

    The Cartesian product of all lines generates variants:
    S-Red, S-Blue, S-Green, M-Red, M-Blue, M-Green, L-Red, ...
    """

    __tablename__ = "product_template_attribute_lines"
    __table_args__ = (
        UniqueConstraint(
            "product_template_id", "attribute_id",
            name="uq_product_tmpl_attr_lines_tmpl_attr",
        ),
        Index("ix_product_tmpl_attr_lines_tmpl", "product_template_id"),
    )

    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_attributes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))

    attribute: Mapped["ProductAttribute"] = relationship(lazy="selectin")
    value_ids: Mapped[list["ProductAttributeValue"]] = relationship(
        secondary=template_attribute_line_values,
        lazy="selectin",
    )
    template_values: Mapped[list["ProductTemplateAttributeValue"]] = relationship(
        back_populates="attribute_line",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ProductTemplateAttributeLine attr={self.attribute_id} tmpl={self.product_template_id}>"


# Many-to-many: excluded combinations between template attribute values
template_attribute_value_exclusions = Table(
    "product_tmpl_attr_value_exclusions",
    Base.metadata,
    mapped_column("ptav_id", ForeignKey("product_template_attribute_values.id", ondelete="CASCADE"), primary_key=True),
    mapped_column("excluded_ptav_id", ForeignKey("product_template_attribute_values.id", ondelete="CASCADE"), primary_key=True),
)


class ProductTemplateAttributeValue(UUIDMixin, TimestampMixin, Base):
    """Per-template customization of an attribute value.

    Allows setting a price extra and defining incompatible value
    combinations (exclusions) that should not generate variants.

    Example: Template "T-Shirt" has Color=Red with price_extra=5.00,
    and Color=Gold is excluded from Size=S (no small gold shirts).
    """

    __tablename__ = "product_template_attribute_values"
    __table_args__ = (
        UniqueConstraint(
            "attribute_line_id", "product_attribute_value_id",
            name="uq_product_tmpl_attr_values_line_value",
        ),
        Index("ix_product_tmpl_attr_values_template", "product_template_id"),
    )

    attribute_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_template_attribute_lines.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_attribute_value_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_attribute_values.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    price_extra: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Extra price added to the base price when this value is selected.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    attribute_line: Mapped["ProductTemplateAttributeLine"] = relationship(
        back_populates="template_values",
    )
    attribute_value: Mapped["ProductAttributeValue"] = relationship(lazy="selectin")
    excluded_values: Mapped[list["ProductTemplateAttributeValue"]] = relationship(
        secondary=template_attribute_value_exclusions,
        primaryjoin="ProductTemplateAttributeValue.id == product_tmpl_attr_value_exclusions.c.ptav_id",
        secondaryjoin="ProductTemplateAttributeValue.id == product_tmpl_attr_value_exclusions.c.excluded_ptav_id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ProductTemplateAttributeValue value={self.product_attribute_value_id} extra={self.price_extra}>"
