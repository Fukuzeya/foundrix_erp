"""Pydantic schemas for VAT validation and partner autocomplete."""

from pydantic import BaseModel


class VATLookupResult(BaseModel):
    """Result of a VAT number validation lookup."""

    valid: bool
    vat_number: str
    company_name: str | None = None
    address: str | None = None
    country_code: str | None = None
    error: str | None = None


class PartnerSuggestion(BaseModel):
    """Suggested partner details derived from a VAT number lookup."""

    name: str | None = None
    street: str | None = None
    city: str | None = None
    zip_code: str | None = None
    country_code: str | None = None
    vat_number: str
