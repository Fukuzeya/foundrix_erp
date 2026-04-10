"""Currency Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


# ── Currency ──────────────────────────────────────────────────────────

class CurrencyCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=3, description="ISO 4217 code")
    name: str = Field(..., min_length=1, max_length=100)
    symbol: str = Field(default="", max_length=10)
    decimal_places: int = Field(default=2, ge=0, le=6)
    rounding: float = Field(default=0.01, gt=0)
    position: str = Field(default="before", pattern="^(before|after)$")
    is_active: bool = True


class CurrencyRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    symbol: str
    decimal_places: int
    rounding: float
    position: str
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class CurrencyUpdate(BaseModel):
    name: str | None = None
    symbol: str | None = None
    decimal_places: int | None = None
    rounding: float | None = None
    position: str | None = None
    is_active: bool | None = None


# ── Currency Rate ─────────────────────────────────────────────────────

class CurrencyRateCreate(BaseModel):
    currency_id: uuid.UUID
    date: date
    rate: float = Field(..., gt=0)


class CurrencyRateRead(BaseModel):
    id: uuid.UUID
    currency_id: uuid.UUID
    date: date
    rate: float
    inverse_rate: float
    created_at: datetime
    model_config = {"from_attributes": True}


class CurrencyRateUpdate(BaseModel):
    rate: float = Field(..., gt=0)


# ── Conversion ────────────────────────────────────────────────────────

class CurrencyConvertRequest(BaseModel):
    amount: float
    from_currency: str = Field(..., min_length=3, max_length=3)
    to_currency: str = Field(..., min_length=3, max_length=3)
    date: date | None = None  # defaults to today


class CurrencyConvertResponse(BaseModel):
    amount: float
    from_currency: str
    to_currency: str
    converted_amount: float
    rate: float
    date: date
