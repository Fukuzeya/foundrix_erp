"""Pydantic schemas for Payment and BatchPayment.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
- Filter: query parameters for list/search endpoints
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

VALID_PAYMENT_TYPES = {"inbound", "outbound"}
VALID_PARTNER_TYPES = {"customer", "supplier"}
VALID_PAYMENT_STATES = {"draft", "posted", "reconciled", "cancelled"}


# ── Payment ──────────────────────────────────────────────────────────


class PaymentCreate(BaseModel):
    """Schema for creating a new payment."""

    payment_type: str = Field(..., max_length=20)
    partner_type: str = Field(..., max_length=20)
    amount: float = Field(..., gt=0)
    currency_code: str = Field(default="USD", min_length=2, max_length=3)
    date: date | None = None
    partner_id: uuid.UUID | None = None
    journal_id: uuid.UUID
    payment_method_id: uuid.UUID | None = None
    invoice_ids: list[uuid.UUID] | None = None
    ref: str | None = Field(None, max_length=200)
    memo: str | None = None
    is_internal_transfer: bool = False
    destination_account_id: uuid.UUID | None = None

    @field_validator("payment_type")
    @classmethod
    def validate_payment_type(cls, v: str) -> str:
        if v not in VALID_PAYMENT_TYPES:
            raise ValueError(
                f"Invalid payment_type '{v}'. Must be one of: {sorted(VALID_PAYMENT_TYPES)}"
            )
        return v

    @field_validator("partner_type")
    @classmethod
    def validate_partner_type(cls, v: str) -> str:
        if v not in VALID_PARTNER_TYPES:
            raise ValueError(
                f"Invalid partner_type '{v}'. Must be one of: {sorted(VALID_PARTNER_TYPES)}"
            )
        return v


class PaymentUpdate(BaseModel):
    """Schema for partial payment update. All fields optional."""

    amount: float | None = Field(None, gt=0)
    currency_code: str | None = Field(None, min_length=2, max_length=3)
    date: date | None = None
    partner_id: uuid.UUID | None = None
    payment_method_id: uuid.UUID | None = None
    ref: str | None = None
    memo: str | None = None


class PaymentRead(BaseModel):
    """Full payment representation."""

    id: uuid.UUID
    payment_type: str
    partner_type: str
    state: str
    amount: float
    currency_code: str
    date: date

    partner_id: uuid.UUID | None
    journal_id: uuid.UUID
    payment_method_id: uuid.UUID | None
    destination_account_id: uuid.UUID | None
    move_id: uuid.UUID | None
    batch_payment_id: uuid.UUID | None

    is_internal_transfer: bool
    is_reconciled: bool
    is_matched: bool

    ref: str | None
    memo: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentReadBrief(BaseModel):
    """Brief payment representation for listing."""

    id: uuid.UUID
    payment_type: str
    partner_type: str
    state: str
    amount: float
    currency_code: str
    date: date
    partner_id: uuid.UUID | None
    ref: str | None

    model_config = {"from_attributes": True}


class PaymentFilter(BaseModel):
    """Query parameters for filtering payments."""

    state: str | None = None
    payment_type: str | None = None
    partner_type: str | None = None
    partner_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


# ── BatchPayment ─────────────────────────────────────────────────────


class BatchPaymentCreate(BaseModel):
    """Schema for creating a batch payment."""

    name: str = Field(..., min_length=1, max_length=200)
    batch_type: str = Field(..., pattern=r"^(inbound|outbound)$")
    date: date | None = None
    journal_id: uuid.UUID
    payment_ids: list[uuid.UUID] | None = None


class BatchPaymentRead(BaseModel):
    """Full batch payment representation."""

    id: uuid.UUID
    name: str
    batch_type: str
    state: str
    date: date
    journal_id: uuid.UUID

    payments: list[PaymentReadBrief] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
