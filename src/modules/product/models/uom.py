"""Unit of Measure models.

Follows Odoo 19's hierarchical UoM model where UoMs relate to a reference
unit through a conversion factor tree. Two UoMs can convert between each
other only if they share a common root reference.

Examples:
    - kg (reference) → g (factor=0.001) → mg (factor=0.000001)
    - m (reference) → cm (factor=0.01) → mm (factor=0.001)
    - Unit (reference) → Dozen (factor=12)
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class UomCategory(UUIDMixin, TimestampMixin, Base):
    """Grouping of related UoMs (e.g. Weight, Length, Volume, Unit).

    UoMs within the same category can be converted between each other.
    Cross-category conversion is not allowed.
    """

    __tablename__ = "uom_categories"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    uoms: Mapped[list["Uom"]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<UomCategory name={self.name!r}>"


class Uom(UUIDMixin, TimestampMixin, Base):
    """A unit of measure with a conversion factor relative to a reference unit.

    Within each category, exactly one UoM should have ``factor=1.0`` and
    ``uom_type='reference'``. All other UoMs define their conversion as::

        quantity_in_reference = quantity * factor   (if uom_type='smaller')
        quantity_in_reference = quantity * factor   (if uom_type='bigger')

    The ``factor`` field stores the ratio: 1 reference = ``factor`` of this UoM.
    For example, if reference is 'kg':
        - g:  factor = 1000  (1 kg = 1000 g),  rounding_factor = 1000/1 → store as ratio
        - lb: factor = 2.20462

    Internally we store ``ratio`` = how many of this unit make 1 reference unit.
    So: ``quantity_in_ref = quantity / ratio``
    And: ``quantity_in_this = quantity_in_ref * ratio``
    """

    __tablename__ = "uoms"
    __table_args__ = (
        CheckConstraint("ratio > 0", name="ck_uoms_positive_ratio"),
        Index("ix_uoms_category_id", "category_id"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uom_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    uom_type: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'reference'"),
        doc="One of: reference, bigger, smaller.",
    )
    ratio: Mapped[float] = mapped_column(
        Float,
        server_default=text("1.0"),
        doc="How many of this unit = 1 reference unit. Reference has ratio=1.",
    )
    rounding: Mapped[float] = mapped_column(
        Float,
        server_default=text("0.01"),
        doc="Rounding precision for this UoM.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    category: Mapped["UomCategory"] = relationship(back_populates="uoms")

    def convert(self, qty: float, to_uom: "Uom") -> float:
        """Convert a quantity from this UoM to another UoM in the same category.

        Raises ValueError if UoMs are in different categories.
        """
        if self.category_id != to_uom.category_id:
            raise ValueError(
                f"Cannot convert between '{self.name}' ({self.category_id}) "
                f"and '{to_uom.name}' ({to_uom.category_id}): different categories"
            )
        if self.id == to_uom.id:
            return qty

        # Convert to reference first, then to target
        qty_in_ref = qty / self.ratio
        result = qty_in_ref * to_uom.ratio

        # Apply rounding
        if to_uom.rounding:
            result = round(result / to_uom.rounding) * to_uom.rounding

        return result

    def __repr__(self) -> str:
        return f"<Uom name={self.name!r} type={self.uom_type} ratio={self.ratio}>"
