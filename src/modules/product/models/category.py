"""Product Category model — hierarchical product classification.

Follows Odoo's product.category pattern with materialized path for
efficient hierarchy queries. Categories can have custom property
definitions that products in the category inherit.
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class ProductCategory(UUIDMixin, TimestampMixin, Base):
    """Hierarchical product classification.

    Example tree:
        All Products
        ├── Physical Products
        │   ├── Electronics
        │   │   ├── Phones
        │   │   └── Laptops
        │   └── Furniture
        └── Services
    """

    __tablename__ = "product_categories"
    __table_args__ = (
        Index("ix_product_categories_parent_id", "parent_id"),
        Index("ix_product_categories_complete_name", "complete_name"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    complete_name: Mapped[str | None] = mapped_column(
        String(1000), nullable=True,
        doc="Computed full path: 'All / Electronics / Phones'.",
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_categories.id", ondelete="CASCADE"),
        nullable=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    parent: Mapped["ProductCategory | None"] = relationship(
        "ProductCategory",
        remote_side="ProductCategory.id",
        foreign_keys=[parent_id],
    )
    children: Mapped[list["ProductCategory"]] = relationship(
        "ProductCategory",
        foreign_keys=[parent_id],
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<ProductCategory name={self.name!r}>"
