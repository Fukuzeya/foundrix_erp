"""Recurring invoice models — templates for automated invoice generation."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Column, String, Float, Boolean, Integer, Date, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
import enum

from src.core.database.base import Base, UUIDMixin, TimestampMixin


class RecurringFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUALLY = "semi_annually"
    YEARLY = "yearly"


class RecurringTemplate(Base, UUIDMixin, TimestampMixin):
    """Template for generating recurring invoices.

    Defines the partner, products, frequency, and schedule for
    automatically creating invoices (e.g., monthly subscription billing).
    """
    __tablename__ = "recurring_invoice_templates"

    name = Column(String(200), nullable=False)
    partner_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # FK to contacts.partner
    journal_id = Column(UUID(as_uuid=True), nullable=False)  # FK to accounting.journal

    # Schedule
    frequency = Column(SAEnum(RecurringFrequency), nullable=False, default=RecurringFrequency.MONTHLY)
    next_invoice_date = Column(Date, nullable=False, default=date.today)
    end_date = Column(Date, nullable=True)  # None = no end date

    # Invoice defaults
    currency_code = Column(String(3), nullable=False, default="USD")
    payment_term_id = Column(UUID(as_uuid=True), nullable=True)
    fiscal_position_id = Column(UUID(as_uuid=True), nullable=True)
    incoterm_id = Column(UUID(as_uuid=True), ForeignKey("incoterms.id"), nullable=True)

    # Automation
    auto_send = Column(Boolean, nullable=False, default=False)  # auto-send by email
    auto_post = Column(Boolean, nullable=False, default=True)  # auto-post (confirm) invoice

    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    note = Column(Text, nullable=True)  # internal note

    # Relationships
    lines = relationship("RecurringTemplateLine", back_populates="template", cascade="all, delete-orphan")

    @property
    def is_expired(self) -> bool:
        return self.end_date is not None and date.today() > self.end_date

    def __repr__(self) -> str:
        return f"<RecurringTemplate {self.name} ({self.frequency.value})>"


class RecurringTemplateLine(Base, UUIDMixin, TimestampMixin):
    """Line item in a recurring invoice template."""
    __tablename__ = "recurring_invoice_template_lines"

    template_id = Column(UUID(as_uuid=True), ForeignKey("recurring_invoice_templates.id"), nullable=False)
    sequence = Column(Integer, nullable=False, default=10)

    # Product (optional — can be a service line without product)
    product_id = Column(UUID(as_uuid=True), nullable=True)
    name = Column(String(500), nullable=False)  # line description
    account_id = Column(UUID(as_uuid=True), nullable=False)  # income/expense account

    # Quantities & pricing
    quantity = Column(Float, nullable=False, default=1.0)
    price_unit = Column(Float, nullable=False, default=0.0)
    discount = Column(Float, nullable=False, default=0.0)  # percentage

    # Tax (stored as JSON array of tax UUIDs)
    tax_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=True, default=list)

    # Relationships
    template = relationship("RecurringTemplate", back_populates="lines")

    @property
    def price_subtotal(self) -> float:
        return round(self.quantity * self.price_unit * (1 - self.discount / 100), 2)

    def __repr__(self) -> str:
        return f"<RecurringTemplateLine {self.name}: {self.quantity} x {self.price_unit}>"
