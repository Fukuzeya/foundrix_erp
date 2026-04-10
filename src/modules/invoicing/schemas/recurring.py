"""Recurring invoice template schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class RecurringLineCreate(BaseModel):
    product_id: uuid.UUID | None = None
    name: str = Field(..., min_length=1)
    account_id: uuid.UUID
    quantity: float = Field(default=1.0, gt=0)
    price_unit: float = Field(default=0.0)
    discount: float = Field(default=0.0, ge=0, le=100)
    tax_ids: list[uuid.UUID] = Field(default_factory=list)
    sequence: int = 10


class RecurringLineRead(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    sequence: int
    product_id: uuid.UUID | None
    name: str
    account_id: uuid.UUID
    quantity: float
    price_unit: float
    discount: float
    tax_ids: list[uuid.UUID] | None
    price_subtotal: float
    model_config = {"from_attributes": True}


class RecurringTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    partner_id: uuid.UUID
    journal_id: uuid.UUID
    frequency: str = Field(default="monthly", pattern="^(daily|weekly|monthly|quarterly|semi_annually|yearly)$")
    next_invoice_date: date
    end_date: date | None = None
    currency_code: str = Field(default="USD", max_length=3)
    payment_term_id: uuid.UUID | None = None
    fiscal_position_id: uuid.UUID | None = None
    incoterm_id: uuid.UUID | None = None
    auto_send: bool = False
    auto_post: bool = True
    note: str | None = None
    lines: list[RecurringLineCreate] = Field(default_factory=list)


class RecurringTemplateRead(BaseModel):
    id: uuid.UUID
    name: str
    partner_id: uuid.UUID
    journal_id: uuid.UUID
    frequency: str
    next_invoice_date: date
    end_date: date | None
    currency_code: str
    payment_term_id: uuid.UUID | None
    fiscal_position_id: uuid.UUID | None
    incoterm_id: uuid.UUID | None
    auto_send: bool
    auto_post: bool
    is_active: bool
    note: str | None
    lines: list[RecurringLineRead] = []
    created_at: datetime
    model_config = {"from_attributes": True}


class RecurringTemplateUpdate(BaseModel):
    name: str | None = None
    frequency: str | None = None
    next_invoice_date: date | None = None
    end_date: date | None = None
    currency_code: str | None = None
    payment_term_id: uuid.UUID | None = None
    fiscal_position_id: uuid.UUID | None = None
    incoterm_id: uuid.UUID | None = None
    auto_send: bool | None = None
    auto_post: bool | None = None
    is_active: bool | None = None
    note: str | None = None
