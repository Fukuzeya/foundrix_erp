"""Pydantic schemas for InvoiceTemplate CRUD operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class InvoiceTemplateCreate(BaseModel):
    """Schema for creating a new invoice template."""

    name: str = Field(..., min_length=1, max_length=200)
    is_default: bool = False
    company_logo_url: str | None = Field(default=None, max_length=500)
    primary_color: str = Field(default="#4F46E5", pattern=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    secondary_color: str = Field(default="#6B7280", pattern=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    font_family: str = Field(default="Helvetica", max_length=100)
    show_logo: bool = True
    show_payment_qr: bool = False
    show_payment_terms: bool = True
    show_tax_details: bool = True
    header_text: str | None = None
    footer_text: str | None = None
    terms_and_conditions: str | None = None
    paper_format: str = Field(default="A4", pattern=r"^(A4|Letter)$")
    is_active: bool = True


class InvoiceTemplateUpdate(BaseModel):
    """Schema for updating an existing invoice template.

    All fields are optional — only provided fields are updated.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_default: bool | None = None
    company_logo_url: str | None = Field(default=None, max_length=500)
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    secondary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    font_family: str | None = Field(default=None, max_length=100)
    show_logo: bool | None = None
    show_payment_qr: bool | None = None
    show_payment_terms: bool | None = None
    show_tax_details: bool | None = None
    header_text: str | None = None
    footer_text: str | None = None
    terms_and_conditions: str | None = None
    paper_format: str | None = Field(default=None, pattern=r"^(A4|Letter)$")
    is_active: bool | None = None


class InvoiceTemplateRead(BaseModel):
    """Schema for reading an invoice template."""

    id: uuid.UUID
    name: str
    is_default: bool
    company_logo_url: str | None
    primary_color: str
    secondary_color: str
    font_family: str
    show_logo: bool
    show_payment_qr: bool
    show_payment_terms: bool
    show_tax_details: bool
    header_text: str | None
    footer_text: str | None
    terms_and_conditions: str | None
    paper_format: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
