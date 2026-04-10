"""Pydantic schemas for Tax and TaxRepartitionLine.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

VALID_TYPE_TAX_USE = {"sale", "purchase", "none"}
VALID_AMOUNT_TYPES = {"percent", "fixed", "division", "group"}
VALID_TAX_EXIGIBILITY = {"on_invoice", "on_payment"}


# ── TaxRepartitionLine ───────────────────────────────────────────────


class TaxRepartitionLineCreate(BaseModel):
    """Schema for creating a tax repartition line."""

    document_type: str = Field(..., pattern=r"^(invoice|refund)$")
    repartition_type: str = Field(..., pattern=r"^(base|tax)$")
    factor_percent: float = 100.0
    account_id: uuid.UUID | None = None
    sequence: int = 1


class TaxRepartitionLineRead(BaseModel):
    """Schema for reading a tax repartition line."""

    id: uuid.UUID
    tax_id: uuid.UUID
    document_type: str
    repartition_type: str
    factor_percent: float
    account_id: uuid.UUID | None
    sequence: int

    model_config = {"from_attributes": True}


# ── Tax ──────────────────────────────────────────────────────────────


class TaxCreate(BaseModel):
    """Schema for creating a new tax."""

    name: str = Field(..., min_length=1, max_length=200)
    type_tax_use: str = Field(..., max_length=20)
    amount_type: str = Field(default="percent", max_length=20)
    amount: float = 0.0
    price_include: bool = False
    include_base_amount: bool = False
    is_base_affected: bool = True
    tax_exigibility: str = "on_invoice"
    cash_basis_transition_account_id: uuid.UUID | None = None
    description: str | None = None
    invoice_label: str | None = Field(None, max_length=200)
    sequence: int = 1

    @field_validator("type_tax_use")
    @classmethod
    def validate_type_tax_use(cls, v: str) -> str:
        if v not in VALID_TYPE_TAX_USE:
            raise ValueError(
                f"Invalid type_tax_use '{v}'. Must be one of: {sorted(VALID_TYPE_TAX_USE)}"
            )
        return v

    @field_validator("amount_type")
    @classmethod
    def validate_amount_type(cls, v: str) -> str:
        if v not in VALID_AMOUNT_TYPES:
            raise ValueError(
                f"Invalid amount_type '{v}'. Must be one of: {sorted(VALID_AMOUNT_TYPES)}"
            )
        return v

    @field_validator("tax_exigibility")
    @classmethod
    def validate_tax_exigibility(cls, v: str) -> str:
        if v not in VALID_TAX_EXIGIBILITY:
            raise ValueError(
                f"Invalid tax_exigibility '{v}'. Must be one of: {sorted(VALID_TAX_EXIGIBILITY)}"
            )
        return v


class TaxUpdate(BaseModel):
    """Schema for partial tax update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    type_tax_use: str | None = None
    amount_type: str | None = None
    amount: float | None = None
    price_include: bool | None = None
    include_base_amount: bool | None = None
    is_base_affected: bool | None = None
    tax_exigibility: str | None = None
    cash_basis_transition_account_id: uuid.UUID | None = None
    description: str | None = None
    invoice_label: str | None = None
    sequence: int | None = None
    is_active: bool | None = None

    @field_validator("type_tax_use")
    @classmethod
    def validate_type_tax_use(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_TYPE_TAX_USE:
            raise ValueError(
                f"Invalid type_tax_use '{v}'. Must be one of: {sorted(VALID_TYPE_TAX_USE)}"
            )
        return v

    @field_validator("amount_type")
    @classmethod
    def validate_amount_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_AMOUNT_TYPES:
            raise ValueError(
                f"Invalid amount_type '{v}'. Must be one of: {sorted(VALID_AMOUNT_TYPES)}"
            )
        return v


class TaxRead(BaseModel):
    """Full tax representation with nested repartition lines."""

    id: uuid.UUID
    name: str
    type_tax_use: str
    amount_type: str
    amount: float
    sequence: int
    is_active: bool
    description: str | None

    price_include: bool
    include_base_amount: bool
    is_base_affected: bool

    tax_exigibility: str
    cash_basis_transition_account_id: uuid.UUID | None
    invoice_label: str | None

    invoice_repartition_lines: list[TaxRepartitionLineRead] = []
    refund_repartition_lines: list[TaxRepartitionLineRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaxReadBrief(BaseModel):
    """Minimal tax representation for foreign key displays."""

    id: uuid.UUID
    name: str
    type_tax_use: str
    amount_type: str
    amount: float
    is_active: bool

    model_config = {"from_attributes": True}


# ── Tax Computation ──────────────────────────────────────────────────


class TaxComputeRequest(BaseModel):
    """Request to compute taxes for a base amount."""

    base: float
    quantity: float = 1.0
    price_unit: float | None = None
    tax_ids: list[uuid.UUID]


class TaxComputeResult(BaseModel):
    """Result of a single tax computation."""

    tax_id: uuid.UUID
    name: str
    amount: float
    base: float
