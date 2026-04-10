"""Currency and exchange rate models — used across all modules for multi-currency support."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Column, String, Float, Boolean, Integer, Date, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.core.database.base import Base, UUIDMixin, TimestampMixin


class Currency(Base, UUIDMixin, TimestampMixin):
    """ISO 4217 currency with formatting preferences."""
    __tablename__ = "currencies"

    code = Column(String(3), unique=True, nullable=False, index=True)  # ISO 4217: USD, EUR, KES
    name = Column(String(100), nullable=False)  # US Dollar, Euro, Kenyan Shilling
    symbol = Column(String(10), nullable=False, default="")  # $, €, KSh
    decimal_places = Column(Integer, nullable=False, default=2)
    rounding = Column(Float, nullable=False, default=0.01)  # smallest currency unit
    position = Column(String(10), nullable=False, default="before")  # before or after amount
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    rates = relationship("CurrencyRate", back_populates="currency", order_by="CurrencyRate.date.desc()")

    def __repr__(self) -> str:
        return f"<Currency {self.code}>"


class CurrencyRate(Base, UUIDMixin, TimestampMixin):
    """Exchange rate for a currency on a specific date.

    Rate is expressed as: 1 unit of company currency = rate units of this currency.
    For example, if company currency is USD and rate for EUR is 0.92,
    then 1 USD = 0.92 EUR.
    """
    __tablename__ = "currency_rates"
    __table_args__ = (
        UniqueConstraint("currency_id", "date", name="uq_currency_rate_date"),
    )

    currency_id = Column(UUID(as_uuid=True), ForeignKey("currencies.id"), nullable=False)
    date = Column(Date, nullable=False, default=date.today)
    rate = Column(Float, nullable=False, default=1.0)  # inverse rate (company currency → this currency)
    inverse_rate = Column(Float, nullable=False, default=1.0)  # this currency → company currency

    # Relationships
    currency = relationship("Currency", back_populates="rates")

    def __repr__(self) -> str:
        return f"<CurrencyRate {self.currency_id} {self.date}: {self.rate}>"
