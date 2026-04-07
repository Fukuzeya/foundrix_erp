"""Pydantic schemas for the Contacts module.

Schemas follow a strict separation:
- Create: fields required/optional at creation time
- Read: fields returned by the API (from_attributes=True)
- Update: all fields optional (partial update)
- Filter: query parameters for list/search endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Partner ───────────────────────────────────────────────────────────


class PartnerCreate(BaseModel):
    """Schema for creating a new partner."""

    name: str = Field(..., min_length=1, max_length=255)
    is_company: bool = False
    partner_type: str = Field(default="contact", pattern=r"^(contact|invoice|delivery|other)$")
    parent_id: uuid.UUID | None = None
    ref: str | None = None

    # Contact info
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    mobile: str | None = Field(None, max_length=50)
    website: str | None = None
    function: str | None = None

    # Address
    street: str | None = None
    street2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country_code: str | None = Field(None, min_length=2, max_length=3)
    country_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    # Classification
    industry_id: uuid.UUID | None = None
    is_customer: bool = False
    is_vendor: bool = False
    tag_ids: list[str] | None = None

    # Tax
    vat: str | None = None
    company_registry: str | None = None

    # Localization
    lang: str | None = None
    tz: str | None = None
    currency_code: str | None = None

    notes: str | None = None

    @field_validator("website", mode="before")
    @classmethod
    def normalize_website(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            return f"https://{v}"
        return v


class PartnerUpdate(BaseModel):
    """Schema for partial partner update. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=255)
    is_company: bool | None = None
    partner_type: str | None = Field(None, pattern=r"^(contact|invoice|delivery|other)$")
    parent_id: uuid.UUID | None = None
    ref: str | None = None

    email: EmailStr | None = None
    phone: str | None = None
    mobile: str | None = None
    website: str | None = None
    function: str | None = None

    street: str | None = None
    street2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    industry_id: uuid.UUID | None = None
    is_customer: bool | None = None
    is_vendor: bool | None = None
    tag_ids: list[str] | None = None

    vat: str | None = None
    company_registry: str | None = None

    lang: str | None = None
    tz: str | None = None
    currency_code: str | None = None

    notes: str | None = None
    is_active: bool | None = None

    @field_validator("website", mode="before")
    @classmethod
    def normalize_website(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            return f"https://{v}"
        return v


class PartnerReadBrief(BaseModel):
    """Minimal partner representation for lists and foreign key displays."""

    id: uuid.UUID
    name: str | None
    display_name: str | None
    email: str | None
    phone: str | None
    is_company: bool
    is_customer: bool
    is_vendor: bool
    is_active: bool

    model_config = {"from_attributes": True}


class AddressRead(BaseModel):
    """Embedded address read schema."""

    id: uuid.UUID
    address_type: str
    label: str | None
    street: str | None
    street2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    country_code: str | None
    country_name: str | None
    is_default: bool

    model_config = {"from_attributes": True}


class BankAccountRead(BaseModel):
    """Embedded bank account read schema."""

    id: uuid.UUID
    account_number: str
    account_name: str | None
    bank_name: str | None
    bank_code: str | None
    branch_name: str | None
    branch_code: str | None
    currency_code: str | None
    is_primary: bool
    allow_outbound: bool

    model_config = {"from_attributes": True}


class IndustryRead(BaseModel):
    """Industry read schema."""

    id: uuid.UUID
    name: str
    full_name: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class PartnerRead(BaseModel):
    """Full partner representation with nested relationships."""

    id: uuid.UUID
    name: str | None
    display_name: str | None
    ref: str | None
    is_company: bool
    is_active: bool
    color: int
    partner_type: str

    # Hierarchy
    parent_id: uuid.UUID | None
    commercial_partner_id: uuid.UUID | None

    # Contact
    email: str | None
    phone: str | None
    mobile: str | None
    website: str | None
    function: str | None

    # Primary address
    street: str | None
    street2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    country_code: str | None
    country_name: str | None
    latitude: float | None
    longitude: float | None

    # Classification
    industry_id: uuid.UUID | None
    industry: IndustryRead | None = None
    is_customer: bool
    is_vendor: bool
    tag_ids: list[str] | None

    # Tax
    vat: str | None
    company_registry: str | None

    # Localization
    lang: str | None
    tz: str | None
    currency_code: str | None

    notes: str | None

    # Nested
    addresses: list[AddressRead] = []
    bank_accounts: list[BankAccountRead] = []
    children: list[PartnerReadBrief] = []

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PartnerFilter(BaseModel):
    """Query parameters for filtering partners."""

    search: str | None = Field(None, description="Search name, email, ref, phone")
    is_company: bool | None = None
    is_customer: bool | None = None
    is_vendor: bool | None = None
    is_active: bool | None = Field(True, description="Default: active only")
    partner_type: str | None = None
    parent_id: uuid.UUID | None = None
    country_code: str | None = None
    industry_id: uuid.UUID | None = None
    tag_id: str | None = Field(None, description="Filter by a single tag UUID")


# ── Address ───────────────────────────────────────────────────────────


class AddressCreate(BaseModel):
    address_type: str = Field(default="other", pattern=r"^(invoice|delivery|other)$")
    label: str | None = None
    street: str | None = None
    street2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    is_default: bool = False


class AddressUpdate(BaseModel):
    address_type: str | None = None
    label: str | None = None
    street: str | None = None
    street2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    is_default: bool | None = None


# ── Bank Account ──────────────────────────────────────────────────────


class BankAccountCreate(BaseModel):
    account_number: str = Field(..., min_length=1, max_length=50)
    account_name: str | None = None
    bank_name: str | None = None
    bank_code: str | None = None
    branch_name: str | None = None
    branch_code: str | None = None
    currency_code: str | None = None
    is_primary: bool = False
    allow_outbound: bool = False
    notes: str | None = None


class BankAccountUpdate(BaseModel):
    account_number: str | None = None
    account_name: str | None = None
    bank_name: str | None = None
    bank_code: str | None = None
    branch_name: str | None = None
    branch_code: str | None = None
    currency_code: str | None = None
    is_primary: bool | None = None
    allow_outbound: bool | None = None
    notes: str | None = None


# ── Category ──────────────────────────────────────────────────────────


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None
    color: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None
    color: int | None = None
    is_active: bool | None = None


class CategoryRead(BaseModel):
    id: uuid.UUID
    name: str
    color: int
    parent_id: uuid.UUID | None
    full_path: str | None
    is_active: bool

    model_config = {"from_attributes": True}


# ── Industry ──────────────────────────────────────────────────────────


class IndustryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    full_name: str | None = None
