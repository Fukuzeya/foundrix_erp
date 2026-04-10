"""Pydantic schemas for Account and AccountTag.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
- Filter: query parameters for list/search endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.modules.accounting.models.account import ACCOUNT_TYPE_GROUPS


# Valid values for validation
VALID_ACCOUNT_TYPES = set(ACCOUNT_TYPE_GROUPS.keys())
VALID_INTERNAL_GROUPS = {"asset", "liability", "equity", "income", "expense", "off"}


# ── AccountTag ───────────────────────────────────────────────────────


class AccountTagCreate(BaseModel):
    """Schema for creating an account tag."""

    name: str = Field(..., min_length=1, max_length=200)
    applicability: str = Field(
        default="accounts", pattern=r"^(accounts|taxes)$",
    )
    color: int = 0


class AccountTagRead(BaseModel):
    """Schema for reading an account tag."""

    id: uuid.UUID
    name: str
    applicability: str
    color: int
    is_active: bool

    model_config = {"from_attributes": True}


# ── Account ──────────────────────────────────────────────────────────


class AccountCreate(BaseModel):
    """Schema for creating a new account."""

    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=500)
    account_type: str = Field(..., max_length=30)
    reconcile: bool = False
    currency_code: str | None = Field(None, min_length=2, max_length=3)
    parent_id: uuid.UUID | None = None
    description: str | None = None
    non_trade: bool = False

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        if v not in VALID_ACCOUNT_TYPES:
            raise ValueError(
                f"Invalid account_type '{v}'. Must be one of: {sorted(VALID_ACCOUNT_TYPES)}"
            )
        return v


class AccountUpdate(BaseModel):
    """Schema for partial account update. All fields optional."""

    code: str | None = Field(None, min_length=1, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=500)
    account_type: str | None = Field(None, max_length=30)
    reconcile: bool | None = None
    currency_code: str | None = Field(None, min_length=2, max_length=3)
    parent_id: uuid.UUID | None = None
    description: str | None = None
    non_trade: bool | None = None
    is_active: bool | None = None

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_ACCOUNT_TYPES:
            raise ValueError(
                f"Invalid account_type '{v}'. Must be one of: {sorted(VALID_ACCOUNT_TYPES)}"
            )
        return v


class AccountRead(BaseModel):
    """Full account representation."""

    id: uuid.UUID
    code: str
    name: str
    account_type: str
    internal_group: str
    reconcile: bool
    is_active: bool
    currency_code: str | None
    parent_id: uuid.UUID | None
    description: str | None
    non_trade: bool
    include_initial_balance: bool

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountReadBrief(BaseModel):
    """Minimal account representation for foreign key displays."""

    id: uuid.UUID
    code: str
    name: str
    account_type: str
    internal_group: str
    is_active: bool

    model_config = {"from_attributes": True}


class AccountFilter(BaseModel):
    """Query parameters for filtering accounts."""

    search: str | None = Field(None, description="Search code or name")
    account_type: str | None = None
    internal_group: str | None = None
    reconcile: bool | None = None
    is_active: bool | None = Field(True, description="Default: active only")
