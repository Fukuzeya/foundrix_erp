"""VAT number validation and partner autocomplete service.

Validates EU VAT numbers by format and provides a stub for VIES API
integration. Returns partner suggestions based on VAT lookups.
"""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ValidationError
from src.modules.invoicing.schemas.vat import PartnerSuggestion, VATLookupResult

logger = logging.getLogger(__name__)

# EU VAT number regex patterns by country code
EU_VAT_PATTERNS: dict[str, str] = {
    "AT": r"ATU\d{8}",
    "BE": r"BE[01]\d{9}",
    "BG": r"BG\d{9,10}",
    "CY": r"CY\d{8}[A-Z]",
    "CZ": r"CZ\d{8,10}",
    "DE": r"DE\d{9}",
    "DK": r"DK\d{8}",
    "EE": r"EE\d{9}",
    "ES": r"ES[A-Z0-9]\d{7}[A-Z0-9]",
    "FI": r"FI\d{8}",
    "FR": r"FR[A-Z0-9]{2}\d{9}",
    "GR": r"EL\d{9}",
    "HR": r"HR\d{11}",
    "HU": r"HU\d{8}",
    "IE": r"IE\d{7}[A-Z]{1,2}",
    "IT": r"IT\d{11}",
    "LT": r"LT(\d{9}|\d{12})",
    "LU": r"LU\d{8}",
    "LV": r"LV\d{11}",
    "MT": r"MT\d{8}",
    "NL": r"NL\d{9}B\d{2}",
    "PL": r"PL\d{10}",
    "PT": r"PT\d{9}",
    "RO": r"RO\d{2,10}",
    "SE": r"SE\d{12}",
    "SI": r"SI\d{8}",
    "SK": r"SK\d{10}",
}


class VATAutocompleteService:
    """Validates EU VAT numbers and provides partner autocomplete suggestions.

    Format validation uses country-specific regex patterns. The VIES API
    integration is stubbed -- in production, replace _call_vies_api with
    a real HTTP call to the EU VIES SOAP/REST service.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def lookup_vat(self, vat_number: str) -> VATLookupResult:
        """Validate a VAT number and look up associated company data.

        Checks the format against known EU patterns, then performs a
        (stubbed) VIES API lookup for valid formats.

        Args:
            vat_number: The VAT number to validate (e.g. "DE123456789").

        Returns:
            VATLookupResult with validity flag and company details.
        """
        cleaned = vat_number.strip().replace(" ", "").replace("-", "").upper()

        if len(cleaned) < 4:
            return VATLookupResult(
                valid=False,
                vat_number=cleaned,
                error="VAT number is too short.",
            )

        if not self.validate_vat_format(cleaned):
            return VATLookupResult(
                valid=False,
                vat_number=cleaned,
                error=f"Invalid VAT format for number: {cleaned}",
            )

        # Stub VIES API call -- returns placeholder data for valid formats
        country_code = self._extract_country_code(cleaned)
        return VATLookupResult(
            valid=True,
            vat_number=cleaned,
            company_name=f"Company ({cleaned})",
            address=f"Registered address for {cleaned}",
            country_code=country_code,
        )

    def validate_vat_format(self, vat_number: str) -> bool:
        """Check whether a VAT number matches a known EU country format.

        Args:
            vat_number: Cleaned, uppercase VAT number.

        Returns:
            True if the number matches a known pattern.
        """
        cleaned = vat_number.strip().replace(" ", "").replace("-", "").upper()

        for country_code, pattern in EU_VAT_PATTERNS.items():
            if re.fullmatch(pattern, cleaned):
                return True

        return False

    async def autocomplete_partner(self, vat_number: str) -> PartnerSuggestion:
        """Look up a VAT number and return a partner suggestion.

        Args:
            vat_number: The VAT number to look up.

        Returns:
            PartnerSuggestion with company details from the lookup.

        Raises:
            ValidationError: If the VAT number format is invalid.
        """
        result = await self.lookup_vat(vat_number)

        if not result.valid:
            raise ValidationError(
                f"Cannot autocomplete partner: {result.error}",
                details={"vat_number": result.vat_number},
            )

        return PartnerSuggestion(
            name=result.company_name,
            street=None,
            city=None,
            zip_code=None,
            country_code=result.country_code,
            vat_number=result.vat_number,
        )

    def _extract_country_code(self, vat_number: str) -> str | None:
        """Extract the two-letter country code from a VAT number.

        Handles the special case where Greece uses 'EL' prefix but the
        ISO country code is 'GR'.
        """
        if len(vat_number) < 2:
            return None

        prefix = vat_number[:2]

        # Greece uses EL in VAT but GR as ISO country code
        if prefix == "EL":
            return "GR"

        # Check if the prefix is a known country code
        if prefix in EU_VAT_PATTERNS:
            return prefix

        return None
