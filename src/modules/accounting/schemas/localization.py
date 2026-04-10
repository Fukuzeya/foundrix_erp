"""Pydantic schemas for Fiscal Localization Packages.

Schemas cover:
- Package listing and detail views
- Installation requests and results
- Template entry structures for charts of accounts and taxes
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ── Template entry schemas ────────────────────────────────────────────


class ChartTemplateEntry(BaseModel):
    """A single account definition within a chart of accounts template."""

    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=500)
    account_type: str = Field(..., max_length=30)
    internal_group: str = Field(..., max_length=20)
    reconcile: bool = False
    is_active: bool = True


class TaxTemplateEntry(BaseModel):
    """A single tax definition within a tax template."""

    name: str = Field(..., min_length=1, max_length=200)
    type_tax_use: str = Field(..., max_length=20)
    amount_type: str = Field(default="percent", max_length=20)
    amount: float = 0.0
    description: str | None = None
    tax_group: str | None = None

    @field_validator("type_tax_use")
    @classmethod
    def validate_type_tax_use(cls, v: str) -> str:
        if v not in {"sale", "purchase", "none"}:
            raise ValueError(
                f"Invalid type_tax_use '{v}'. Must be one of: none, purchase, sale"
            )
        return v

    @field_validator("amount_type")
    @classmethod
    def validate_amount_type(cls, v: str) -> str:
        if v not in {"percent", "fixed", "division", "group"}:
            raise ValueError(
                f"Invalid amount_type '{v}'. Must be one of: division, fixed, group, percent"
            )
        return v


# ── Package schemas ───────────────────────────────────────────────────


class LocalizationPackageSummary(BaseModel):
    """Minimal package representation for listing available localizations."""

    country_code: str
    country_name: str
    currency_code: str
    description: str | None = None

    model_config = {"from_attributes": True}


class LocalizationPackageRead(BaseModel):
    """Full localization package representation."""

    id: uuid.UUID
    country_code: str
    country_name: str
    currency_code: str
    version: str
    description: str | None

    chart_template_data: dict | None = None
    tax_template_data: dict | None = None
    fiscal_position_data: dict | None = None

    legal_statement_types: list[str] | None = None
    date_format: str
    decimal_separator: str
    thousands_separator: str
    fiscal_year_start_month: int
    fiscal_year_start_day: int
    is_active: bool

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Installation schemas ──────────────────────────────────────────────


class LocalizationInstallRequest(BaseModel):
    """Request to install a localization package."""

    country_code: str = Field(..., min_length=2, max_length=2)
    company_id: uuid.UUID | None = None
    install_chart: bool = True
    install_taxes: bool = True
    install_fiscal_positions: bool = True

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, v: str) -> str:
        return v.upper()


class LocalizationInstallResult(BaseModel):
    """Result of a localization package installation."""

    accounts_created: int = 0
    taxes_created: int = 0
    fiscal_positions_created: int = 0
    status: str = "completed"
    errors: list[str] = Field(default_factory=list)


# ── Install log schema ───────────────────────────────────────────────


class LocalizationInstallLogRead(BaseModel):
    """Read schema for installation log entries."""

    id: uuid.UUID
    package_id: uuid.UUID
    company_id: uuid.UUID | None
    installed_at: datetime
    accounts_created: int
    taxes_created: int
    fiscal_positions_created: int
    status: str
    error_message: str | None
    installed_by: uuid.UUID | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
