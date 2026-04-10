"""Schemas for fiscal position integration in invoicing workflows."""

import uuid

from pydantic import BaseModel


class FiscalPositionMapping(BaseModel):
    """Result of applying a fiscal position to a set of taxes."""

    original_tax_ids: list[uuid.UUID]
    mapped_tax_ids: list[uuid.UUID]
    fiscal_position_id: uuid.UUID
    fiscal_position_name: str


class FiscalPositionSuggestion(BaseModel):
    """Suggested fiscal position for a partner/country combination."""

    fiscal_position_id: uuid.UUID | None
    fiscal_position_name: str | None
    country_code: str | None
    is_eu: bool = False
    reason: str


class InvoiceTaxApplication(BaseModel):
    """Result of applying fiscal position + tax rules to invoice lines."""

    line_index: int
    original_tax_ids: list[uuid.UUID]
    applied_tax_ids: list[uuid.UUID]
    tax_amount: float
    reason: str = ""


class OSSInfo(BaseModel):
    """One-Stop-Shop (OSS) tax information for EU cross-border sales."""

    is_oss_applicable: bool
    origin_country: str | None = None
    destination_country: str | None = None
    oss_tax_rate: float | None = None
    explanation: str = ""
