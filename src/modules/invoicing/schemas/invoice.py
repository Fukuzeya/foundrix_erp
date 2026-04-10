"""Invoice-specific schemas — simplified views on top of accounting moves."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class InvoiceLineInput(BaseModel):
    """Simplified invoice line input (maps to MoveLineCreate internally)."""
    product_id: uuid.UUID | None = None
    name: str = Field(..., min_length=1)
    account_id: uuid.UUID
    quantity: float = Field(default=1.0, gt=0)
    price_unit: float = Field(default=0.0)
    discount: float = Field(default=0.0, ge=0, le=100)
    tax_ids: list[uuid.UUID] = Field(default_factory=list)


class CreateCustomerInvoice(BaseModel):
    """Simplified customer invoice creation."""
    partner_id: uuid.UUID
    invoice_date: date | None = None
    invoice_date_due: date | None = None
    journal_id: uuid.UUID | None = None  # auto-selects sale journal if None
    currency_code: str | None = None
    payment_term_id: uuid.UUID | None = None
    fiscal_position_id: uuid.UUID | None = None
    incoterm_id: uuid.UUID | None = None
    ref: str | None = None
    narration: str | None = None
    lines: list[InvoiceLineInput] = Field(default_factory=list)


class CreateVendorBill(BaseModel):
    """Simplified vendor bill creation."""
    partner_id: uuid.UUID
    invoice_date: date | None = None
    invoice_date_due: date | None = None
    journal_id: uuid.UUID | None = None  # auto-selects purchase journal if None
    currency_code: str | None = None
    payment_term_id: uuid.UUID | None = None
    fiscal_position_id: uuid.UUID | None = None
    ref: str | None = None  # vendor reference
    narration: str | None = None
    lines: list[InvoiceLineInput] = Field(default_factory=list)


class CreateCreditNote(BaseModel):
    """Credit note creation from an existing invoice."""
    invoice_id: uuid.UUID
    reason: str = Field(default="", max_length=500)
    reversal_date: date | None = None  # defaults to today
    use_refund_journal: bool = False


class DuplicateInvoice(BaseModel):
    """Duplicate an invoice as a new draft."""
    invoice_id: uuid.UUID
    new_date: date | None = None


class RegisterPaymentRequest(BaseModel):
    """Register a payment against one or more invoices."""
    partner_id: uuid.UUID
    amount: float = Field(..., gt=0)
    journal_id: uuid.UUID  # bank/cash journal
    payment_date: date | None = None
    invoice_ids: list[uuid.UUID] = Field(default_factory=list)
    currency_code: str | None = None
    memo: str | None = None


class InvoiceSummary(BaseModel):
    """Lightweight invoice read for lists."""
    id: uuid.UUID
    name: str | None
    move_type: str
    partner_id: uuid.UUID | None
    invoice_date: date | None
    invoice_date_due: date | None
    amount_untaxed: float
    amount_tax: float
    amount_total: float
    amount_residual: float
    amount_paid: float
    payment_state: str
    state: str
    currency_code: str
    model_config = {"from_attributes": True}


class InvoiceAnalysis(BaseModel):
    """Invoice analysis report entry."""
    period: str  # YYYY-MM
    invoice_count: int
    total_amount: float
    total_paid: float
    total_outstanding: float
    average_days_to_pay: float | None


class AgingBucket(BaseModel):
    """Aging report entry per partner."""
    partner_id: uuid.UUID | None
    partner_name: str | None = None
    current: float = 0.0
    days_1_30: float = 0.0
    days_31_60: float = 0.0
    days_61_90: float = 0.0
    days_90_plus: float = 0.0
    total: float = 0.0


class TopPartnerEntry(BaseModel):
    """Top customer/vendor ranking entry."""
    partner_id: uuid.UUID
    invoice_count: int
    total_amount: float
    total_paid: float


class PaymentPerformance(BaseModel):
    """Payment performance metrics."""
    average_days_to_pay: float | None
    on_time_count: int
    on_time_percent: float
    late_count: int
    late_percent: float
    total_invoices: int


class RevenueTrendEntry(BaseModel):
    """Monthly revenue trend entry."""
    period: str  # YYYY-MM
    revenue: float
    expense: float
    net: float


class OutstandingSummary(BaseModel):
    """Outstanding amounts summary by direction."""
    customer_outstanding: float
    vendor_outstanding: float
    net_outstanding: float
