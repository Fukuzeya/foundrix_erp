"""Credit control schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreditControlCreate(BaseModel):
    partner_id: uuid.UUID
    credit_limit: float = Field(default=0.0, ge=0)
    on_hold: bool = False
    warning_threshold: float = Field(default=0.9, ge=0, le=1.0)
    note: str | None = None


class CreditControlRead(BaseModel):
    id: uuid.UUID
    partner_id: uuid.UUID
    credit_limit: float
    on_hold: bool
    warning_threshold: float
    note: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class CreditControlUpdate(BaseModel):
    credit_limit: float | None = None
    on_hold: bool | None = None
    warning_threshold: float | None = None
    note: str | None = None


class CreditCheckResult(BaseModel):
    """Result of a credit limit check for a partner."""
    partner_id: uuid.UUID
    credit_limit: float
    current_outstanding: float
    available_credit: float
    usage_percent: float
    on_hold: bool
    status: str  # "ok", "warning", "exceeded", "on_hold"
