"""Pydantic schemas for e-invoicing configuration, generation, and status."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ── Config schemas ────────────────────────────────────────────────────


class EInvoiceConfigCreate(BaseModel):
    """Payload for creating a new e-invoice configuration."""

    name: str
    format_type: str
    country_code: str | None = None
    eas_code: str | None = None
    endpoint_id: str | None = None
    is_default: bool = False
    settings: dict | None = None


class EInvoiceConfigRead(BaseModel):
    """Full representation of an e-invoice configuration."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    format_type: str
    country_code: str | None
    eas_code: str | None
    endpoint_id: str | None
    is_default: bool
    is_active: bool
    settings: dict | None
    created_at: datetime
    updated_at: datetime


class EInvoiceConfigUpdate(BaseModel):
    """Partial update payload for e-invoice configuration."""

    name: str | None = None
    country_code: str | None = None
    eas_code: str | None = None
    endpoint_id: str | None = None
    is_default: bool | None = None
    is_active: bool | None = None
    settings: dict | None = None


# ── Log schemas ───────────────────────────────────────────────────────


class EInvoiceLogRead(BaseModel):
    """Full representation of an e-invoice transmission log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    move_id: uuid.UUID
    format_type: str
    direction: str
    status: str
    xml_content: str | None
    file_name: str | None
    error_message: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    external_id: str | None
    created_at: datetime
    updated_at: datetime


# ── Generation schemas ────────────────────────────────────────────────


class EInvoiceGenerateRequest(BaseModel):
    """Request to generate an e-invoice XML document."""

    move_id: uuid.UUID
    format_type: str
    validate_only: bool = False


class EInvoiceGenerateResponse(BaseModel):
    """Result of an e-invoice generation attempt."""

    success: bool
    xml_content: str | None = None
    validation_errors: list[str] = []
    file_name: str | None = None


# ── Status schema ─────────────────────────────────────────────────────


class EInvoiceStatus(BaseModel):
    """Current transmission status of an e-invoice."""

    move_id: uuid.UUID
    format_type: str
    status: str
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
