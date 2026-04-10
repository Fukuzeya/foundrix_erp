"""Pydantic schemas for Asset and AssetGroup.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

VALID_ASSET_TYPES = {"asset", "expense", "revenue"}
VALID_METHODS = {"linear", "degressive"}
VALID_METHOD_PERIODS = {"1", "3", "6", "12"}
VALID_PRORATA_TYPES = {"daily_computation", "constant_periods"}
VALID_ASSET_STATES = {"draft", "open", "paused", "close", "cancelled"}


# ── AssetGroup ───────────────────────────────────────────────────────


class AssetGroupCreate(BaseModel):
    """Schema for creating an asset group / depreciation profile."""

    name: str = Field(..., min_length=1, max_length=200)
    asset_type: str = Field(..., max_length=20)
    method: str = "linear"
    method_number: int = Field(default=60, gt=0)
    method_period: str = "1"
    method_progress_factor: float = 0.3
    prorata_computation_type: str = "daily_computation"
    account_asset_id: uuid.UUID | None = None
    account_depreciation_id: uuid.UUID | None = None
    account_expense_depreciation_id: uuid.UUID | None = None
    journal_id: uuid.UUID | None = None

    @field_validator("asset_type")
    @classmethod
    def validate_asset_type(cls, v: str) -> str:
        if v not in VALID_ASSET_TYPES:
            raise ValueError(
                f"Invalid asset_type '{v}'. Must be one of: {sorted(VALID_ASSET_TYPES)}"
            )
        return v

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in VALID_METHODS:
            raise ValueError(
                f"Invalid method '{v}'. Must be one of: {sorted(VALID_METHODS)}"
            )
        return v

    @field_validator("method_period")
    @classmethod
    def validate_method_period(cls, v: str) -> str:
        if v not in VALID_METHOD_PERIODS:
            raise ValueError(
                f"Invalid method_period '{v}'. Must be one of: {sorted(VALID_METHOD_PERIODS)}"
            )
        return v


class AssetGroupUpdate(BaseModel):
    """Schema for partial asset group update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    asset_type: str | None = None
    method: str | None = None
    method_number: int | None = Field(None, gt=0)
    method_period: str | None = None
    method_progress_factor: float | None = None
    prorata_computation_type: str | None = None
    account_asset_id: uuid.UUID | None = None
    account_depreciation_id: uuid.UUID | None = None
    account_expense_depreciation_id: uuid.UUID | None = None
    journal_id: uuid.UUID | None = None
    is_active: bool | None = None


class AssetGroupRead(BaseModel):
    """Full asset group representation."""

    id: uuid.UUID
    name: str
    asset_type: str
    method: str
    method_number: int
    method_period: str
    method_progress_factor: float
    prorata_computation_type: str
    account_asset_id: uuid.UUID | None
    account_depreciation_id: uuid.UUID | None
    account_expense_depreciation_id: uuid.UUID | None
    journal_id: uuid.UUID | None
    is_active: bool

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── AssetDepreciationLine ────────────────────────────────────────────


class AssetDepreciationLineRead(BaseModel):
    """Schema for reading an asset depreciation line."""

    id: uuid.UUID
    asset_id: uuid.UUID
    date: date
    depreciation_value: float
    cumulative_depreciation: float
    remaining_value: float
    move_id: uuid.UUID | None
    state: str
    sequence: int

    model_config = {"from_attributes": True}


# ── Asset ────────────────────────────────────────────────────────────


class AssetCreate(BaseModel):
    """Schema for creating a fixed asset."""

    name: str = Field(..., min_length=1, max_length=500)
    asset_type: str = Field(..., max_length=20)
    acquisition_date: date
    first_depreciation_date: date | None = None
    original_value: float = Field(..., gt=0)
    salvage_value: float = Field(default=0.0, ge=0)
    already_depreciated_amount_import: float = 0.0
    currency_code: str = Field(default="USD", min_length=2, max_length=3)

    method: str = "linear"
    method_number: int = Field(default=60, gt=0)
    method_period: str = "1"
    method_progress_factor: float = 0.3
    prorata_computation_type: str = "daily_computation"

    account_asset_id: uuid.UUID | None = None
    account_depreciation_id: uuid.UUID | None = None
    account_expense_depreciation_id: uuid.UUID | None = None
    journal_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    original_move_line_id: uuid.UUID | None = None
    description: str | None = None

    @field_validator("asset_type")
    @classmethod
    def validate_asset_type(cls, v: str) -> str:
        if v not in VALID_ASSET_TYPES:
            raise ValueError(
                f"Invalid asset_type '{v}'. Must be one of: {sorted(VALID_ASSET_TYPES)}"
            )
        return v

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in VALID_METHODS:
            raise ValueError(
                f"Invalid method '{v}'. Must be one of: {sorted(VALID_METHODS)}"
            )
        return v


class AssetUpdate(BaseModel):
    """Schema for partial asset update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=500)
    salvage_value: float | None = Field(None, ge=0)
    method: str | None = None
    method_number: int | None = Field(None, gt=0)
    method_period: str | None = None
    method_progress_factor: float | None = None
    prorata_computation_type: str | None = None
    account_asset_id: uuid.UUID | None = None
    account_depreciation_id: uuid.UUID | None = None
    account_expense_depreciation_id: uuid.UUID | None = None
    journal_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    description: str | None = None


class AssetRead(BaseModel):
    """Full asset representation with depreciation lines."""

    id: uuid.UUID
    name: str
    asset_type: str
    state: str
    acquisition_date: date
    first_depreciation_date: date | None

    original_value: float
    salvage_value: float
    book_value: float
    value_residual: float
    already_depreciated_amount_import: float
    currency_code: str

    method: str
    method_number: int
    method_period: str
    method_progress_factor: float
    prorata_computation_type: str

    account_asset_id: uuid.UUID | None
    account_depreciation_id: uuid.UUID | None
    account_expense_depreciation_id: uuid.UUID | None
    journal_id: uuid.UUID | None
    group_id: uuid.UUID | None
    original_move_line_id: uuid.UUID | None
    description: str | None

    depreciation_lines: list[AssetDepreciationLineRead] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssetReadBrief(BaseModel):
    """Brief asset representation for listing."""

    id: uuid.UUID
    name: str
    asset_type: str
    state: str
    original_value: float
    book_value: float
    currency_code: str
    acquisition_date: date

    model_config = {"from_attributes": True}
