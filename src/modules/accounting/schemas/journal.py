"""Pydantic schemas for Journal.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.modules.accounting.schemas.account import AccountReadBrief

VALID_JOURNAL_TYPES = {"sale", "purchase", "bank", "cash", "general"}


# ── Journal ──────────────────────────────────────────────────────────


class JournalCreate(BaseModel):
    """Schema for creating a new journal."""

    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=7)
    journal_type: str = Field(..., max_length=20)
    default_account_id: uuid.UUID | None = None
    suspense_account_id: uuid.UUID | None = None
    profit_account_id: uuid.UUID | None = None
    loss_account_id: uuid.UUID | None = None
    currency_code: str | None = Field(None, min_length=2, max_length=3)
    sequence_prefix: str | None = Field(None, max_length=50)
    description: str | None = None

    @field_validator("journal_type")
    @classmethod
    def validate_journal_type(cls, v: str) -> str:
        if v not in VALID_JOURNAL_TYPES:
            raise ValueError(
                f"Invalid journal_type '{v}'. Must be one of: {sorted(VALID_JOURNAL_TYPES)}"
            )
        return v


class JournalUpdate(BaseModel):
    """Schema for partial journal update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    code: str | None = Field(None, min_length=1, max_length=7)
    journal_type: str | None = Field(None, max_length=20)
    default_account_id: uuid.UUID | None = None
    suspense_account_id: uuid.UUID | None = None
    profit_account_id: uuid.UUID | None = None
    loss_account_id: uuid.UUID | None = None
    currency_code: str | None = Field(None, min_length=2, max_length=3)
    sequence_prefix: str | None = Field(None, max_length=50)
    use_separate_refund_sequence: bool | None = None
    refund_sequence_prefix: str | None = None
    restrict_mode_hash_table: bool | None = None
    description: str | None = None
    is_active: bool | None = None

    @field_validator("journal_type")
    @classmethod
    def validate_journal_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_JOURNAL_TYPES:
            raise ValueError(
                f"Invalid journal_type '{v}'. Must be one of: {sorted(VALID_JOURNAL_TYPES)}"
            )
        return v


class JournalRead(BaseModel):
    """Full journal representation."""

    id: uuid.UUID
    name: str
    code: str
    journal_type: str
    is_active: bool
    sequence: int

    default_account_id: uuid.UUID | None
    default_account: AccountReadBrief | None = None
    suspense_account_id: uuid.UUID | None
    profit_account_id: uuid.UUID | None
    loss_account_id: uuid.UUID | None

    currency_code: str | None
    sequence_prefix: str | None
    sequence_next_number: int
    use_separate_refund_sequence: bool
    refund_sequence_prefix: str | None
    refund_sequence_next_number: int

    restrict_mode_hash_table: bool
    description: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JournalReadBrief(BaseModel):
    """Minimal journal representation for foreign key displays."""

    id: uuid.UUID
    name: str
    code: str
    journal_type: str
    is_active: bool

    model_config = {"from_attributes": True}
