"""Pydantic schemas for InvoiceBatchPayment and BatchPaymentLine.

Schemas follow the project convention:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Summary: lightweight listing representation
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

VALID_BATCH_TYPES = {"outbound", "inbound"}
VALID_PAYMENT_METHODS = {"sepa_credit", "sepa_debit", "check", "wire", "manual"}
VALID_BATCH_STATES = {"draft", "confirmed", "sent", "reconciled", "cancelled"}
VALID_LINE_STATES = {"pending", "paid", "failed"}


# ── BatchPaymentLine schemas ─────────────────────────────────────────


class BatchPaymentLineCreate(BaseModel):
    """Schema for adding a line to a batch payment."""

    partner_id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    amount: float = Field(..., gt=0)
    partner_bank_account: str | None = Field(None, max_length=34)
    partner_bic: str | None = Field(None, max_length=11)
    communication: str | None = Field(None, max_length=200)


class BatchPaymentLineRead(BaseModel):
    """Full batch payment line representation."""

    id: uuid.UUID
    batch_id: uuid.UUID
    partner_id: uuid.UUID
    invoice_id: uuid.UUID | None
    amount: float
    currency_code: str
    partner_bank_account: str | None
    partner_bic: str | None
    communication: str | None
    state: str
    payment_id: uuid.UUID | None
    error_message: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── BatchPayment schemas ─────────────────────────────────────────────


class BatchPaymentCreate(BaseModel):
    """Schema for creating a new invoice batch payment."""

    batch_type: str = Field(..., max_length=20)
    payment_method: str = Field(..., max_length=20)
    journal_id: uuid.UUID
    currency_code: str = Field(default="USD", min_length=2, max_length=3)
    execution_date: date | None = None
    note: str | None = None

    @field_validator("batch_type")
    @classmethod
    def validate_batch_type(cls, v: str) -> str:
        if v not in VALID_BATCH_TYPES:
            raise ValueError(
                f"Invalid batch_type '{v}'. Must be one of: {sorted(VALID_BATCH_TYPES)}"
            )
        return v

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v: str) -> str:
        if v not in VALID_PAYMENT_METHODS:
            raise ValueError(
                f"Invalid payment_method '{v}'. Must be one of: {sorted(VALID_PAYMENT_METHODS)}"
            )
        return v


class BatchPaymentRead(BaseModel):
    """Full batch payment representation including lines."""

    id: uuid.UUID
    name: str
    batch_type: str
    payment_method: str
    journal_id: uuid.UUID
    currency_code: str
    total_amount: float
    payment_count: int
    state: str
    execution_date: date | None
    generated_filename: str | None
    note: str | None

    lines: list[BatchPaymentLineRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchPaymentSummary(BaseModel):
    """Lightweight batch payment representation for listings."""

    id: uuid.UUID
    name: str
    batch_type: str
    state: str
    total_amount: float
    payment_count: int
    execution_date: date | None

    model_config = {"from_attributes": True}
