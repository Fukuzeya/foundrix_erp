"""Pydantic schemas for vendor bill import and email alias endpoints."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel


# ── Parsed bill structures ───────────────────────────────────────────


class ParsedBillLine(BaseModel):
    """A single line item extracted from a vendor bill document."""

    description: str
    quantity: float = 1.0
    unit_price: float
    amount: float
    tax_rate: float | None = None


class ParsedBillData(BaseModel):
    """Structured data extracted from a vendor bill document."""

    vendor_name: str | None = None
    invoice_number: str | None = None
    date: date | None = None
    due_date: date | None = None
    total: float | None = None
    tax_amount: float | None = None
    currency: str = "USD"
    lines: list[ParsedBillLine] = []


# ── Vendor bill import schemas ───────────────────────────────────────


class VendorBillImportCreate(BaseModel):
    source_type: str
    file_name: str | None = None
    file_content_type: str | None = None
    email_from: str | None = None
    email_subject: str | None = None


class VendorBillImportRead(BaseModel):
    id: uuid.UUID
    source_type: str
    file_name: str | None
    file_content_type: str | None
    email_from: str | None
    email_subject: str | None
    status: str
    parsed_data: dict | None
    partner_id: uuid.UUID | None
    move_id: uuid.UUID | None
    total_amount: float | None
    invoice_number: str | None
    invoice_date: date | None
    error_message: str | None
    processing_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Email alias schemas ──────────────────────────────────────────────


class VendorBillEmailAliasCreate(BaseModel):
    alias_email: str
    target_journal_id: uuid.UUID | None = None
    auto_create: bool = False


class VendorBillEmailAliasRead(BaseModel):
    id: uuid.UUID
    alias_email: str
    target_journal_id: uuid.UUID | None
    auto_create: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VendorBillEmailAliasUpdate(BaseModel):
    target_journal_id: uuid.UUID | None = None
    auto_create: bool | None = None
    is_active: bool | None = None


# ── Summary ──────────────────────────────────────────────────────────


class ImportSummary(BaseModel):
    """Aggregated counts of vendor bill imports by status."""

    total_imports: int
    pending: int
    processing: int
    parsed: int
    created: int
    failed: int
