"""Pydantic schemas for PaymentTerm, PaymentTermLine, and FiscalPosition.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

VALID_VALUE_TYPES = {"percent", "fixed", "balance"}
VALID_DELAY_TYPES = {
    "days_after_invoice",
    "days_after_end_of_month",
    "days_after_end_of_next_month",
}


# ── PaymentTermLine ──────────────────────────────────────────────────


class PaymentTermLineCreate(BaseModel):
    """Schema for creating a payment term line."""

    value_type: str = Field(default="balance", max_length=20)
    value_amount: float = 0.0
    delay_type: str = "days_after_invoice"
    nb_days: int = Field(default=0, ge=0)
    sequence: int = 10

    @field_validator("value_type")
    @classmethod
    def validate_value_type(cls, v: str) -> str:
        if v not in VALID_VALUE_TYPES:
            raise ValueError(
                f"Invalid value_type '{v}'. Must be one of: {sorted(VALID_VALUE_TYPES)}"
            )
        return v

    @field_validator("delay_type")
    @classmethod
    def validate_delay_type(cls, v: str) -> str:
        if v not in VALID_DELAY_TYPES:
            raise ValueError(
                f"Invalid delay_type '{v}'. Must be one of: {sorted(VALID_DELAY_TYPES)}"
            )
        return v


class PaymentTermLineRead(BaseModel):
    """Schema for reading a payment term line."""

    id: uuid.UUID
    payment_term_id: uuid.UUID
    value_type: str
    value_amount: float
    delay_type: str
    nb_days: int
    sequence: int

    model_config = {"from_attributes": True}


# ── PaymentTerm ──────────────────────────────────────────────────────


class PaymentTermCreate(BaseModel):
    """Schema for creating a payment term."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    display_on_invoice: bool = True
    sequence: int = 10
    early_discount: bool = False
    discount_percentage: float = 0.0
    discount_days: int = 0
    lines: list[PaymentTermLineCreate] = Field(default_factory=list)


class PaymentTermUpdate(BaseModel):
    """Schema for partial payment term update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    display_on_invoice: bool | None = None
    sequence: int | None = None
    early_discount: bool | None = None
    discount_percentage: float | None = None
    discount_days: int | None = None
    is_active: bool | None = None


class PaymentTermRead(BaseModel):
    """Full payment term representation with nested lines."""

    id: uuid.UUID
    name: str
    is_active: bool
    description: str | None
    display_on_invoice: bool
    sequence: int
    early_discount: bool
    discount_percentage: float
    discount_days: int

    lines: list[PaymentTermLineRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── FiscalPositionTax ────────────────────────────────────────────────


class FiscalPositionTaxCreate(BaseModel):
    """Schema for creating a fiscal position tax mapping."""

    tax_src_id: uuid.UUID
    tax_dest_id: uuid.UUID | None = None


class FiscalPositionTaxRead(BaseModel):
    """Schema for reading a fiscal position tax mapping."""

    id: uuid.UUID
    fiscal_position_id: uuid.UUID
    tax_src_id: uuid.UUID
    tax_dest_id: uuid.UUID | None

    model_config = {"from_attributes": True}


# ── FiscalPositionAccount ────────────────────────────────────────────


class FiscalPositionAccountCreate(BaseModel):
    """Schema for creating a fiscal position account mapping."""

    account_src_id: uuid.UUID
    account_dest_id: uuid.UUID


class FiscalPositionAccountRead(BaseModel):
    """Schema for reading a fiscal position account mapping."""

    id: uuid.UUID
    fiscal_position_id: uuid.UUID
    account_src_id: uuid.UUID
    account_dest_id: uuid.UUID

    model_config = {"from_attributes": True}


# ── FiscalPosition ──────────────────────────────────────────────────


class FiscalPositionCreate(BaseModel):
    """Schema for creating a fiscal position."""

    name: str = Field(..., min_length=1, max_length=200)
    sequence: int = 10
    auto_apply: bool = False
    country_code: str | None = Field(None, min_length=2, max_length=3)
    description: str | None = None
    tax_mappings: list[FiscalPositionTaxCreate] = Field(default_factory=list)
    account_mappings: list[FiscalPositionAccountCreate] = Field(default_factory=list)


class FiscalPositionUpdate(BaseModel):
    """Schema for partial fiscal position update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    sequence: int | None = None
    auto_apply: bool | None = None
    country_code: str | None = None
    description: str | None = None
    is_active: bool | None = None


class FiscalPositionRead(BaseModel):
    """Full fiscal position representation with nested mappings."""

    id: uuid.UUID
    name: str
    sequence: int
    is_active: bool
    auto_apply: bool
    country_code: str | None
    description: str | None

    tax_mappings: list[FiscalPositionTaxRead] = []
    account_mappings: list[FiscalPositionAccountRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
