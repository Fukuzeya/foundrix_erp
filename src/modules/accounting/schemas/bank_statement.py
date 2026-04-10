"""Pydantic schemas for BankStatement and BankStatementLine.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


# ── BankStatementLine ────────────────────────────────────────────────


class BankStatementLineCreate(BaseModel):
    """Schema for creating a bank statement line."""

    date: date
    name: str = Field(..., min_length=1, max_length=500)
    ref: str | None = Field(None, max_length=200)
    partner_id: uuid.UUID | None = None
    amount: float
    currency_code: str = Field(default="USD", min_length=2, max_length=3)
    sequence: int = 10
    notes: str | None = None


class BankStatementLineRead(BaseModel):
    """Full bank statement line representation."""

    id: uuid.UUID
    statement_id: uuid.UUID
    date: date
    name: str
    ref: str | None
    partner_id: uuid.UUID | None
    amount: float
    currency_code: str
    sequence: int
    is_reconciled: bool
    move_id: uuid.UUID | None
    notes: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── BankStatement ────────────────────────────────────────────────────


class BankStatementCreate(BaseModel):
    """Schema for creating a bank statement."""

    name: str = Field(..., min_length=1, max_length=200)
    date: date
    journal_id: uuid.UUID
    balance_start: float = 0.0
    balance_end_real: float = 0.0
    import_format: str | None = Field(
        None, pattern=r"^(ofx|csv|camt053|coda|qif|manual)$",
    )
    lines: list[BankStatementLineCreate] = Field(default_factory=list)


class BankStatementUpdate(BaseModel):
    """Schema for partial bank statement update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    date: date | None = None
    balance_start: float | None = None
    balance_end_real: float | None = None


class BankStatementRead(BaseModel):
    """Full bank statement representation with nested lines."""

    id: uuid.UUID
    name: str
    date: date
    journal_id: uuid.UUID
    balance_start: float
    balance_end_real: float
    balance_end: float
    state: str
    import_format: str | None

    lines: list[BankStatementLineRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BankStatementReadBrief(BaseModel):
    """Brief bank statement representation for listing."""

    id: uuid.UUID
    name: str
    date: date
    journal_id: uuid.UUID
    balance_start: float
    balance_end_real: float
    state: str

    model_config = {"from_attributes": True}
