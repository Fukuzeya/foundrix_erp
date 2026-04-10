"""Pydantic schemas for Move (journal entry) and MoveLine (journal item).

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
- Filter: query parameters for list/search endpoints
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

VALID_MOVE_TYPES = {
    "entry", "out_invoice", "out_refund", "in_invoice",
    "in_refund", "out_receipt", "in_receipt",
}
VALID_STATES = {"draft", "posted", "cancel"}
VALID_PAYMENT_STATES = {"not_paid", "partial", "in_payment", "paid", "reversed"}


# ── MoveLine ─────────────────────────────────────────────────────────


class MoveLineCreate(BaseModel):
    """Schema for creating a journal item within a journal entry."""

    account_id: uuid.UUID
    debit: float = Field(default=0.0, ge=0)
    credit: float = Field(default=0.0, ge=0)
    partner_id: uuid.UUID | None = None
    name: str | None = None
    product_id: uuid.UUID | None = None
    quantity: float = 1.0
    price_unit: float = 0.0
    discount: float = Field(default=0.0, ge=0, le=100)
    tax_ids: list[uuid.UUID] | None = None
    date_maturity: date | None = None
    analytic_distribution: dict[str, float] | None = None
    currency_code: str | None = Field(None, min_length=2, max_length=3)
    sequence: int = 10

    @model_validator(mode="after")
    def validate_debit_credit_exclusive(self) -> MoveLineCreate:
        if self.debit > 0 and self.credit > 0:
            raise ValueError("debit and credit cannot both be positive")
        return self


class MoveLineUpdate(BaseModel):
    """Schema for partial move line update. All fields optional."""

    account_id: uuid.UUID | None = None
    debit: float | None = Field(None, ge=0)
    credit: float | None = Field(None, ge=0)
    partner_id: uuid.UUID | None = None
    name: str | None = None
    product_id: uuid.UUID | None = None
    quantity: float | None = None
    price_unit: float | None = None
    discount: float | None = Field(None, ge=0, le=100)
    tax_ids: list[uuid.UUID] | None = None
    date_maturity: date | None = None
    analytic_distribution: dict[str, float] | None = None


class MoveLineRead(BaseModel):
    """Full journal item representation."""

    id: uuid.UUID
    move_id: uuid.UUID
    account_id: uuid.UUID
    partner_id: uuid.UUID | None

    debit: float
    credit: float
    balance: float
    amount_currency: float
    currency_code: str

    display_type: str
    name: str | None
    product_id: uuid.UUID | None
    quantity: float
    price_unit: float
    discount: float
    price_subtotal: float
    price_total: float

    tax_line_id: uuid.UUID | None
    tax_base_amount: float

    date_maturity: date | None
    reconciled: bool
    amount_residual: float
    amount_residual_currency: float
    full_reconcile_id: uuid.UUID | None
    matching_number: str | None

    analytic_distribution: dict[str, float] | None
    sequence: int

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MoveLineReadBrief(BaseModel):
    """Minimal move line for brief move listing."""

    id: uuid.UUID
    account_id: uuid.UUID
    debit: float
    credit: float
    balance: float
    name: str | None
    partner_id: uuid.UUID | None

    model_config = {"from_attributes": True}


# ── Move ─────────────────────────────────────────────────────────────


class MoveCreate(BaseModel):
    """Schema for creating a new journal entry / invoice."""

    move_type: str = Field(default="entry", max_length=20)
    journal_id: uuid.UUID
    date: date | None = None
    partner_id: uuid.UUID | None = None
    currency_code: str = Field(default="USD", min_length=2, max_length=3)
    ref: str | None = Field(None, max_length=200)
    narration: str | None = None
    lines: list[MoveLineCreate] = Field(..., min_length=1)
    payment_term_id: uuid.UUID | None = None
    fiscal_position_id: uuid.UUID | None = None
    invoice_date: date | None = None
    invoice_date_due: date | None = None

    @field_validator("move_type")
    @classmethod
    def validate_move_type(cls, v: str) -> str:
        if v not in VALID_MOVE_TYPES:
            raise ValueError(
                f"Invalid move_type '{v}'. Must be one of: {sorted(VALID_MOVE_TYPES)}"
            )
        return v


class MoveUpdate(BaseModel):
    """Schema for partial move update. All fields optional."""

    date: date | None = None
    partner_id: uuid.UUID | None = None
    currency_code: str | None = Field(None, min_length=2, max_length=3)
    ref: str | None = None
    narration: str | None = None
    payment_term_id: uuid.UUID | None = None
    fiscal_position_id: uuid.UUID | None = None
    invoice_date: date | None = None
    invoice_date_due: date | None = None
    auto_post: str | None = None
    auto_post_until: date | None = None


class MoveRead(BaseModel):
    """Full journal entry representation with nested lines."""

    id: uuid.UUID
    name: str
    ref: str | None
    move_type: str
    state: str
    payment_state: str

    date: date
    invoice_date: date | None
    invoice_date_due: date | None

    journal_id: uuid.UUID
    partner_id: uuid.UUID | None
    fiscal_position_id: uuid.UUID | None
    payment_term_id: uuid.UUID | None

    currency_code: str
    currency_rate: float

    amount_untaxed: float
    amount_tax: float
    amount_total: float
    amount_residual: float
    amount_paid: float

    auto_post: str
    auto_post_until: date | None

    reversed_entry_id: uuid.UUID | None
    narration: str | None

    lines: list[MoveLineRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MoveReadBrief(BaseModel):
    """Brief journal entry representation for listing."""

    id: uuid.UUID
    name: str
    ref: str | None
    move_type: str
    state: str
    payment_state: str
    date: date
    journal_id: uuid.UUID
    partner_id: uuid.UUID | None
    currency_code: str
    amount_total: float
    amount_residual: float

    model_config = {"from_attributes": True}


class MoveFilter(BaseModel):
    """Query parameters for filtering journal entries."""

    search: str | None = Field(None, description="Search name, ref, or partner name")
    move_type: str | None = None
    state: str | None = None
    payment_state: str | None = None
    partner_id: uuid.UUID | None = None
    journal_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    is_posted: bool | None = None
