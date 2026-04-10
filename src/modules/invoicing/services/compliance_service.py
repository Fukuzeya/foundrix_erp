"""Invoice compliance validation service.

Handles country-specific regulatory requirements for invoicing,
VAT number validation, and structured communication generation.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import NotFoundError
from src.modules.accounting.models.move import Move, INVOICE_TYPES
from src.modules.accounting.repositories.move_repo import MoveRepository
from src.modules.invoicing.schemas.compliance import (
    ComplianceResult,
    CountryRequirements,
    VATValidationResult,
)

logger = logging.getLogger(__name__)

# ── EU VAT Number Patterns ────────────────────────────────────────────
# Regex patterns for VAT number format validation per EU member state.
# These validate the format only, not whether the number is actually registered.

VAT_PATTERNS: dict[str, str] = {
    "AT": r"^ATU\d{8}$",
    "BE": r"^BE[01]\d{9}$",
    "BG": r"^BG\d{9,10}$",
    "CY": r"^CY\d{8}[A-Z]$",
    "CZ": r"^CZ\d{8,10}$",
    "DE": r"^DE\d{9}$",
    "DK": r"^DK\d{8}$",
    "EE": r"^EE\d{9}$",
    "ES": r"^ES[A-Z0-9]\d{7}[A-Z0-9]$",
    "FI": r"^FI\d{8}$",
    "FR": r"^FR[A-Z0-9]{2}\d{9}$",
    "GR": r"^EL\d{9}$",
    "HR": r"^HR\d{11}$",
    "HU": r"^HU\d{8}$",
    "IE": r"^IE\d{7}[A-Z]{1,2}$",
    "IT": r"^IT\d{11}$",
    "LT": r"^LT(\d{9}|\d{12})$",
    "LU": r"^LU\d{8}$",
    "LV": r"^LV\d{11}$",
    "MT": r"^MT\d{8}$",
    "NL": r"^NL\d{9}B\d{2}$",
    "PL": r"^PL\d{10}$",
    "PT": r"^PT\d{9}$",
    "RO": r"^RO\d{2,10}$",
    "SE": r"^SE\d{12}$",
    "SI": r"^SI\d{8}$",
    "SK": r"^SK\d{10}$",
}

# ── Country Requirements ──────────────────────────────────────────────
# E-invoicing regulatory requirements by country.

COUNTRY_REQUIREMENTS: dict[str, dict] = {
    "DE": {
        "country_name": "Germany",
        "requires_einvoice": True,
        "einvoice_format": "xrechnung",
        "requirements": [
            "XRechnung format mandatory for B2G invoices",
            "Leitweg-ID required as BuyerReference",
            "VAT number (USt-IdNr.) required on invoices",
            "Invoice must include supplier tax registration",
            "Payment terms must be clearly stated",
        ],
    },
    "IT": {
        "country_name": "Italy",
        "requires_einvoice": True,
        "einvoice_format": "sdi",
        "requirements": [
            "FatturaPA format mandatory via SDI (Sistema di Interscambio)",
            "Codice Destinatario or PEC required for delivery",
            "Progressive invoice numbering per fiscal year",
            "Bollo virtuale for exempt invoices over EUR 77.47",
            "Split payment for B2G transactions",
        ],
    },
    "FR": {
        "country_name": "France",
        "requires_einvoice": True,
        "einvoice_format": "facturx",
        "requirements": [
            "Factur-X format for B2G via Chorus Pro",
            "SIRET number required for French businesses",
            "Mandatory e-invoicing phased rollout (2024-2026)",
            "E-reporting for international B2B transactions",
            "Legal mentions required (e.g. late payment penalties)",
        ],
    },
    "ES": {
        "country_name": "Spain",
        "requires_einvoice": True,
        "einvoice_format": "facturae",
        "requirements": [
            "FacturaE format for B2G invoices via FACe",
            "NIF/CIF tax identification required",
            "SII (Suministro Inmediato de Informacion) reporting",
            "Invoice registration within 4 days of issue",
            "Equivalence surcharge for retail regime",
        ],
    },
    "BE": {
        "country_name": "Belgium",
        "requires_einvoice": True,
        "einvoice_format": "peppol",
        "requirements": [
            "Peppol BIS 3.0 for B2G invoices via Mercurius",
            "Structured communication (+++VVV/VVVV/VVVCC+++) recommended",
            "Enterprise number (KBO/BCE) required",
            "VAT number format: BE + 10 digits",
            "Mandatory e-invoicing for B2G since 2024",
        ],
    },
    "NL": {
        "country_name": "Netherlands",
        "requires_einvoice": True,
        "einvoice_format": "peppol",
        "requirements": [
            "Peppol BIS 3.0 for B2G invoices via Digipoort",
            "KvK (Chamber of Commerce) number required",
            "BTW-nummer (VAT) must be on all invoices",
            "Mandatory e-invoicing for central government",
        ],
    },
    "AT": {
        "country_name": "Austria",
        "requires_einvoice": True,
        "einvoice_format": "peppol",
        "requirements": [
            "E-invoice mandatory for B2G via USP (Unternehmensserviceportal)",
            "Peppol BIS 3.0 or ebInterface supported",
            "UID (VAT) number required",
            "Supplier bank details mandatory",
        ],
    },
    "PT": {
        "country_name": "Portugal",
        "requires_einvoice": True,
        "einvoice_format": "cius-pt",
        "requirements": [
            "CIUS-PT format based on EN 16931",
            "ATCUD (unique document code) mandatory since 2023",
            "SAF-T reporting required",
            "QR code mandatory on invoices",
            "NIF (tax number) required on all invoices",
        ],
    },
    "PL": {
        "country_name": "Poland",
        "requires_einvoice": True,
        "einvoice_format": "ksef",
        "requirements": [
            "KSeF (National e-Invoice System) mandatory",
            "Structured invoice format FA(2)",
            "NIP (tax identification number) required",
            "Real-time invoice reporting to tax authority",
        ],
    },
    "SE": {
        "country_name": "Sweden",
        "requires_einvoice": True,
        "einvoice_format": "peppol",
        "requirements": [
            "Peppol BIS 3.0 mandatory for B2G",
            "Organisationsnummer required",
            "F-skatt registration must be indicated",
            "Momsregistreringsnummer (VAT) required",
        ],
    },
}


class InvoiceComplianceService:
    """Validates invoices against country-specific regulatory requirements."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_repo = MoveRepository(db)

    async def validate_invoice_compliance(
        self, move_id: uuid.UUID, country_code: str
    ) -> ComplianceResult:
        """Validate an invoice against country-specific requirements.

        Checks mandatory fields, format compliance, and regulatory rules
        for the specified country.
        """
        move = await self.move_repo.get_by_id_or_raise(move_id, "Move")

        errors: list[str] = []
        warnings: list[str] = []
        code = country_code.upper()

        # ── Universal checks ──────────────────────────────────────
        if move.move_type not in INVOICE_TYPES:
            errors.append(f"Move '{move.name}' is not an invoice type (got '{move.move_type}')")

        if not move.invoice_date:
            errors.append("Invoice date is required")

        if not move.partner_id:
            errors.append("Partner (customer/vendor) is required")

        if move.amount_total <= 0:
            warnings.append("Invoice total is zero or negative")

        if not move.lines:
            errors.append("Invoice has no lines")

        if move.state == "draft":
            warnings.append("Invoice is still in draft state")

        # ── Country-specific checks ───────────────────────────────
        requirements = COUNTRY_REQUIREMENTS.get(code)

        if requirements:
            if requirements["requires_einvoice"]:
                warnings.append(
                    f"{requirements['country_name']} requires e-invoicing "
                    f"in {requirements['einvoice_format']} format"
                )

            if code == "DE":
                if not move.ref:
                    warnings.append(
                        "German B2G invoices require a Leitweg-ID as buyer reference"
                    )

            elif code == "IT":
                if not move.ref:
                    warnings.append(
                        "Italian invoices require a Codice Destinatario or PEC address"
                    )

            elif code == "FR":
                if not move.ref:
                    warnings.append(
                        "French B2G invoices require a SIRET or service code"
                    )

            elif code == "BE":
                if not move.ref:
                    warnings.append(
                        "Belgian invoices should include structured communication"
                    )

            elif code == "ES":
                if not move.invoice_date:
                    errors.append(
                        "Spanish SII requires invoice date for registration within 4 days"
                    )

            elif code == "PT":
                if not move.ref:
                    warnings.append("Portuguese invoices require ATCUD code")

            elif code == "PL":
                if not move.ref:
                    warnings.append("Polish KSeF invoices require structured reference")

        else:
            warnings.append(
                f"No specific compliance rules configured for country '{code}'"
            )

        # ── Line-level checks ─────────────────────────────────────
        product_lines = [
            line for line in move.lines if line.display_type == "product"
        ]
        for idx, line in enumerate(product_lines, start=1):
            if not line.name:
                errors.append(f"Line {idx}: description is required")
            if line.quantity <= 0:
                errors.append(f"Line {idx}: quantity must be positive")
            if line.price_unit < 0:
                errors.append(f"Line {idx}: unit price cannot be negative")

        is_compliant = len(errors) == 0

        return ComplianceResult(
            is_compliant=is_compliant,
            country_code=code,
            errors=errors,
            warnings=warnings,
        )

    def get_country_requirements(self, country_code: str) -> CountryRequirements:
        """Get the e-invoicing requirements for a given country.

        Returns requirements including mandatory format, regulatory rules,
        and whether e-invoicing is required.
        """
        code = country_code.upper()
        data = COUNTRY_REQUIREMENTS.get(code)

        if data:
            return CountryRequirements(
                country_code=code,
                country_name=data["country_name"],
                requires_einvoice=data["requires_einvoice"],
                einvoice_format=data["einvoice_format"],
                requirements=data["requirements"],
            )

        return CountryRequirements(
            country_code=code,
            country_name=code,
            requires_einvoice=False,
            einvoice_format=None,
            requirements=[],
        )

    def generate_structured_communication(
        self, country_code: str, invoice_number: str
    ) -> str:
        """Generate a structured payment communication reference.

        For Belgium: produces the +++VVV/VVVV/VVVCC+++ format where
        the check digits are modulo 97.

        For other countries: returns a generic structured reference.
        """
        code = country_code.upper()

        if code == "BE":
            return self._generate_belgian_communication(invoice_number)

        # Generic: prefix with country code and zero-pad
        digits = re.sub(r"\D", "", invoice_number)
        if not digits:
            digits = "0"

        padded = digits.zfill(10)[-10:]
        return f"{code}-{padded}"

    def _generate_belgian_communication(self, invoice_number: str) -> str:
        """Generate a Belgian structured communication +++VVV/VVVV/VVVCC+++.

        The format is a 12-digit number split as VVV/VVVV/VVVCC where
        the last 2 digits (CC) are a modulo 97 check on the first 10 digits.
        """
        # Extract numeric part from invoice number
        digits = re.sub(r"\D", "", invoice_number)
        if not digits:
            digits = "0"

        # Take last 10 digits, zero-pad if needed
        base = digits.zfill(10)[-10:]

        # Calculate modulo 97 check digits
        base_int = int(base)
        check = base_int % 97
        if check == 0:
            check = 97

        full = f"{base}{check:02d}"

        # Format as +++VVV/VVVV/VVVCC+++
        return f"+++{full[:3]}/{full[3:7]}/{full[7:]}+++"

    def validate_vat_number(
        self, vat_number: str, country_code: str | None = None
    ) -> VATValidationResult:
        """Validate a VAT number format against EU country patterns.

        If country_code is not provided, it is inferred from the first
        two characters of the VAT number (the country prefix).

        This validates format only — not registration with tax authorities.
        """
        cleaned = vat_number.strip().upper().replace(" ", "").replace(".", "").replace("-", "")

        if len(cleaned) < 4:
            return VATValidationResult(
                is_valid=False,
                vat_number=cleaned,
                country_code=country_code,
                error="VAT number is too short (minimum 4 characters)",
            )

        # Determine country code
        if country_code:
            code = country_code.upper()
        else:
            # Greece uses EL prefix in VAT but GR as country code
            prefix = cleaned[:2]
            if prefix == "EL":
                code = "GR"
            else:
                code = prefix

        pattern = VAT_PATTERNS.get(code)
        if pattern is None:
            return VATValidationResult(
                is_valid=False,
                vat_number=cleaned,
                country_code=code,
                error=f"No VAT pattern configured for country '{code}'",
            )

        if re.match(pattern, cleaned):
            return VATValidationResult(
                is_valid=True,
                vat_number=cleaned,
                country_code=code,
            )

        return VATValidationResult(
            is_valid=False,
            vat_number=cleaned,
            country_code=code,
            error=f"VAT number '{cleaned}' does not match expected format for {code}",
        )
