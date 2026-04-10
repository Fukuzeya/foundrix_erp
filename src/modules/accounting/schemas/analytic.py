"""Pydantic schemas for Analytic Plans, Accounts, and Budgets.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


# ── AnalyticPlan ─────────────────────────────────────────────────────


class AnalyticPlanCreate(BaseModel):
    """Schema for creating an analytic plan."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    sequence: int = 10
    color: int = 0
    parent_id: uuid.UUID | None = None


class AnalyticPlanUpdate(BaseModel):
    """Schema for partial analytic plan update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    sequence: int | None = None
    color: int | None = None
    parent_id: uuid.UUID | None = None
    is_active: bool | None = None


class AnalyticPlanRead(BaseModel):
    """Full analytic plan representation."""

    id: uuid.UUID
    name: str
    description: str | None
    sequence: int
    is_active: bool
    color: int
    parent_id: uuid.UUID | None
    complete_name: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── AnalyticAccount ──────────────────────────────────────────────────


class AnalyticAccountCreate(BaseModel):
    """Schema for creating an analytic account."""

    name: str = Field(..., min_length=1, max_length=200)
    code: str | None = Field(None, max_length=50)
    plan_id: uuid.UUID
    description: str | None = None
    currency_code: str = Field(default="USD", min_length=2, max_length=3)
    parent_id: uuid.UUID | None = None


class AnalyticAccountUpdate(BaseModel):
    """Schema for partial analytic account update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    code: str | None = Field(None, max_length=50)
    plan_id: uuid.UUID | None = None
    description: str | None = None
    currency_code: str | None = Field(None, min_length=2, max_length=3)
    parent_id: uuid.UUID | None = None
    is_active: bool | None = None


class AnalyticAccountRead(BaseModel):
    """Full analytic account representation."""

    id: uuid.UUID
    name: str
    code: str | None
    plan_id: uuid.UUID
    is_active: bool
    description: str | None
    currency_code: str
    parent_id: uuid.UUID | None
    complete_name: str | None
    debit: float
    credit: float
    balance: float

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnalyticAccountReadBrief(BaseModel):
    """Minimal analytic account representation."""

    id: uuid.UUID
    name: str
    code: str | None
    plan_id: uuid.UUID
    is_active: bool

    model_config = {"from_attributes": True}


# ── Budget ───────────────────────────────────────────────────────────


class BudgetLineCreate(BaseModel):
    """Schema for creating a budget line."""

    analytic_account_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    date_from: date
    date_to: date
    planned_amount: float = 0.0


class BudgetLineRead(BaseModel):
    """Schema for reading a budget line."""

    id: uuid.UUID
    budget_id: uuid.UUID
    analytic_account_id: uuid.UUID | None
    account_id: uuid.UUID | None
    date_from: date
    date_to: date
    planned_amount: float
    practical_amount: float

    model_config = {"from_attributes": True}


class BudgetCreate(BaseModel):
    """Schema for creating a budget."""

    name: str = Field(..., min_length=1, max_length=200)
    date_from: date
    date_to: date
    description: str | None = None
    lines: list[BudgetLineCreate] = Field(default_factory=list)


class BudgetUpdate(BaseModel):
    """Schema for partial budget update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    date_from: date | None = None
    date_to: date | None = None
    description: str | None = None
    state: str | None = None


class BudgetRead(BaseModel):
    """Full budget representation with nested lines."""

    id: uuid.UUID
    name: str
    state: str
    date_from: date
    date_to: date
    description: str | None

    lines: list[BudgetLineRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
