"""Incoterm model — international commercial terms (ICC standard)."""

from sqlalchemy import Column, String, Boolean, Text
from src.core.database.base import Base, UUIDMixin, TimestampMixin


class Incoterm(Base, UUIDMixin, TimestampMixin):
    """International Commercial Terms (Incoterms 2020).

    Used on invoices and purchase orders to define responsibilities
    for shipping, insurance, and customs.
    """
    __tablename__ = "incoterms"

    code = Column(String(3), unique=True, nullable=False)  # EXW, FOB, CIF, etc.
    name = Column(String(100), nullable=False)  # Ex Works, Free on Board, etc.
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Incoterm {self.code}: {self.name}>"
