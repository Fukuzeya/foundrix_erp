"""Pydantic schemas for invoice compliance validation and country requirements."""

from pydantic import BaseModel


class ComplianceResult(BaseModel):
    """Result of a country-specific compliance check on an invoice."""

    is_compliant: bool
    country_code: str
    errors: list[str] = []
    warnings: list[str] = []


class CountryRequirements(BaseModel):
    """Regulatory e-invoicing requirements for a specific country."""

    country_code: str
    country_name: str
    requires_einvoice: bool
    einvoice_format: str | None = None
    requirements: list[str] = []


class VATValidationResult(BaseModel):
    """Result of a VAT number format validation."""

    is_valid: bool
    vat_number: str
    country_code: str | None = None
    error: str | None = None
