"""Pydantic schemas for FiscalYear.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


# ── FiscalYear ───────────────────────────────────────────────────────


class FiscalYearCreate(BaseModel):
    """Schema for creating a fiscal year."""

    name: str = Field(..., min_length=1, max_length=200)
    date_from: date
    date_to: date
    last_day: int = Field(default=31, ge=1, le=31)
    last_month: int = Field(default=12, ge=1, le=12)
    description: str | None = None

    @field_validator("date_to")
    @classmethod
    def validate_date_range(cls, v: date, info: object) -> date:
        date_from = info.data.get("date_from") if hasattr(info, "data") else None
        if date_from and v <= date_from:
            raise ValueError("date_to must be after date_from")
        return v


class FiscalYearUpdate(BaseModel):
    """Schema for partial fiscal year update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    date_from: date | None = None
    date_to: date | None = None
    last_day: int | None = Field(None, ge=1, le=31)
    last_month: int | None = Field(None, ge=1, le=12)
    description: str | None = None

    # Lock dates
    sale_lock_date: date | None = None
    purchase_lock_date: date | None = None
    tax_lock_date: date | None = None
    fiscalyear_lock_date: date | None = None
    hard_lock_date: date | None = None

    state: str | None = Field(None, pattern=r"^(open|closed)$")


class FiscalYearRead(BaseModel):
    """Full fiscal year representation."""

    id: uuid.UUID
    name: str
    date_from: date
    date_to: date

    sale_lock_date: date | None
    purchase_lock_date: date | None
    tax_lock_date: date | None
    fiscalyear_lock_date: date | None
    hard_lock_date: date | None

    last_day: int
    last_month: int
    state: str
    description: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
