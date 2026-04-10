"""Credit control models — per-partner credit limits and holds."""

from sqlalchemy import Column, Float, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID

from src.core.database.base import Base, UUIDMixin, TimestampMixin


class CreditControl(Base, UUIDMixin, TimestampMixin):
    """Credit control configuration for a partner.

    Tracks credit limits and hold status. When a partner's outstanding
    invoices exceed the credit limit, the system can warn or block
    new invoice creation.
    """
    __tablename__ = "credit_controls"

    partner_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    credit_limit = Column(Float, nullable=False, default=0.0)  # 0 = unlimited
    on_hold = Column(Boolean, nullable=False, default=False)  # manually block invoicing
    warning_threshold = Column(Float, nullable=False, default=0.9)  # warn at 90% of limit
    note = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CreditControl partner={self.partner_id} limit={self.credit_limit}>"
