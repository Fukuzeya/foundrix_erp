"""Pydantic schemas for Reconciliation models.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

VALID_RULE_TYPES = {"writeoff_button", "writeoff_suggestion", "invoice_matching"}
VALID_MATCH_LABEL_TYPES = {"contains", "not_contains", "match_regex"}
VALID_MATCH_AMOUNT_TYPES = {"lower", "greater", "between"}


# ── ReconcileModelLine ───────────────────────────────────────────────


class ReconcileModelLineCreate(BaseModel):
    """Schema for creating a reconcile model line."""

    account_id: uuid.UUID
    amount_type: str = Field(
        default="percentage",
        pattern=r"^(fixed|percentage|percentage_st_line|regex)$",
    )
    amount_string: str = "100"
    label: str | None = Field(None, max_length=200)
    sequence: int = 10


class ReconcileModelLineRead(BaseModel):
    """Schema for reading a reconcile model line."""

    id: uuid.UUID
    model_id: uuid.UUID
    account_id: uuid.UUID
    amount_type: str
    amount_string: str
    label: str | None
    sequence: int

    model_config = {"from_attributes": True}


# ── ReconcileModel ───────────────────────────────────────────────────


class ReconcileModelCreate(BaseModel):
    """Schema for creating a reconcile model."""

    name: str = Field(..., min_length=1, max_length=200)
    sequence: int = 10
    rule_type: str = "writeoff_button"
    auto_reconcile: bool = False

    match_label: str | None = None
    match_label_param: str | None = Field(None, max_length=500)
    match_amount: str | None = None
    match_amount_min: float | None = None
    match_amount_max: float | None = None
    match_partner: bool = False

    lines: list[ReconcileModelLineCreate] = Field(default_factory=list)

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        if v not in VALID_RULE_TYPES:
            raise ValueError(
                f"Invalid rule_type '{v}'. Must be one of: {sorted(VALID_RULE_TYPES)}"
            )
        return v

    @field_validator("match_label")
    @classmethod
    def validate_match_label(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_MATCH_LABEL_TYPES:
            raise ValueError(
                f"Invalid match_label '{v}'. Must be one of: {sorted(VALID_MATCH_LABEL_TYPES)}"
            )
        return v

    @field_validator("match_amount")
    @classmethod
    def validate_match_amount(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_MATCH_AMOUNT_TYPES:
            raise ValueError(
                f"Invalid match_amount '{v}'. Must be one of: {sorted(VALID_MATCH_AMOUNT_TYPES)}"
            )
        return v


class ReconcileModelUpdate(BaseModel):
    """Schema for partial reconcile model update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    sequence: int | None = None
    rule_type: str | None = None
    auto_reconcile: bool | None = None
    match_label: str | None = None
    match_label_param: str | None = None
    match_amount: str | None = None
    match_amount_min: float | None = None
    match_amount_max: float | None = None
    match_partner: bool | None = None
    is_active: bool | None = None


class ReconcileModelRead(BaseModel):
    """Full reconcile model representation with nested lines."""

    id: uuid.UUID
    name: str
    sequence: int
    rule_type: str
    is_active: bool
    auto_reconcile: bool

    match_label: str | None
    match_label_param: str | None
    match_amount: str | None
    match_amount_min: float | None
    match_amount_max: float | None
    match_partner: bool

    lines: list[ReconcileModelLineRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── PartialReconcile ─────────────────────────────────────────────────


class PartialReconcileRead(BaseModel):
    """Schema for reading a partial reconcile."""

    id: uuid.UUID
    debit_move_line_id: uuid.UUID
    credit_move_line_id: uuid.UUID
    amount: float
    debit_amount_currency: float
    credit_amount_currency: float
    full_reconcile_id: uuid.UUID | None
    exchange_move_id: uuid.UUID | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── FullReconcile ────────────────────────────────────────────────────


class FullReconcileRead(BaseModel):
    """Full reconcile representation with nested partials."""

    id: uuid.UUID
    name: str

    partials: list[PartialReconcileRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
