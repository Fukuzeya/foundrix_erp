"""Fiscal position integration service — wires accounting fiscal positions into invoicing workflows.

Provides tax mapping, fiscal position auto-detection, OSS (One-Stop-Shop) support,
and automatic application of fiscal positions to invoice lines. Delegates fiscal
position and tax data access to the accounting repositories.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move, MoveLine, INVOICE_TYPES
from src.modules.accounting.models.payment_term import (
    FiscalPosition,
    FiscalPositionTax,
)
from src.modules.accounting.models.tax import Tax
from src.modules.accounting.repositories.move_repo import MoveRepository, MoveLineRepository
from src.modules.accounting.repositories.payment_term_repo import FiscalPositionRepository
from src.modules.accounting.repositories.tax_repo import TaxRepository
from src.modules.invoicing.schemas.fiscal_position import (
    FiscalPositionMapping,
    FiscalPositionSuggestion,
    InvoiceTaxApplication,
    OSSInfo,
)

logger = logging.getLogger(__name__)


class FiscalPositionIntegrationService:
    """Integrates accounting fiscal positions into invoicing workflows.

    Handles tax mapping via fiscal position rules, auto-detection of the
    appropriate fiscal position based on partner country/VAT, and EU
    One-Stop-Shop (OSS) determination for cross-border B2C sales.
    """

    EU_COUNTRIES: set[str] = {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
        "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._fiscal_position_repo = FiscalPositionRepository(db)
        self._move_repo = MoveRepository(db)
        self._move_line_repo = MoveLineRepository(db)
        self._tax_repo = TaxRepository(db)

    # ── Public API ────────────────────────────────────────────────────────────

    async def apply_fiscal_position(
        self,
        fiscal_position_id: uuid.UUID,
        tax_ids: list[uuid.UUID],
    ) -> FiscalPositionMapping:
        """Map source taxes to destination taxes using a fiscal position's tax mappings.

        For each tax in *tax_ids*, if the fiscal position has a mapping with that
        tax as ``tax_src_id``, replace it with ``tax_dest_id`` (or remove it if
        ``tax_dest_id`` is None, indicating tax exemption).

        Taxes without a mapping rule are passed through unchanged.
        """
        fiscal_position = await self._fiscal_position_repo.get_by_id(fiscal_position_id)
        if fiscal_position is None:
            raise NotFoundError("fiscal_positions", str(fiscal_position_id))

        if not fiscal_position.is_active:
            raise BusinessRuleError(
                f"Fiscal position '{fiscal_position.name}' is inactive and cannot be applied."
            )

        # Build a lookup: source tax id -> destination tax id (None = exempt)
        src_to_dest: dict[uuid.UUID, uuid.UUID | None] = {}
        for mapping in fiscal_position.tax_mappings:
            src_to_dest[mapping.tax_src_id] = mapping.tax_dest_id

        mapped_tax_ids: list[uuid.UUID] = []
        for tax_id in tax_ids:
            if tax_id in src_to_dest:
                dest_id = src_to_dest[tax_id]
                if dest_id is not None:
                    mapped_tax_ids.append(dest_id)
                # dest_id is None means tax-exempt: skip this tax entirely
            else:
                # No mapping rule — keep the original tax
                mapped_tax_ids.append(tax_id)

        logger.info(
            "Applied fiscal position '%s': %d taxes in -> %d taxes out",
            fiscal_position.name,
            len(tax_ids),
            len(mapped_tax_ids),
        )

        return FiscalPositionMapping(
            original_tax_ids=tax_ids,
            mapped_tax_ids=mapped_tax_ids,
            fiscal_position_id=fiscal_position.id,
            fiscal_position_name=fiscal_position.name,
        )

    async def suggest_fiscal_position(
        self,
        partner_country_code: str,
        is_company: bool = True,
        vat_number: str | None = None,
    ) -> FiscalPositionSuggestion:
        """Suggest a fiscal position based on partner country and VAT status.

        Logic:
        - Domestic (same country as company): no fiscal position needed.
        - EU with valid VAT number (B2B): reverse charge fiscal position.
        - EU without VAT number (B2C): destination country taxes (OSS may apply).
        - Non-EU: export fiscal position (zero-rated / exempt).

        If a matching auto-apply fiscal position exists in the database, it is
        returned. Otherwise, a suggestion with ``fiscal_position_id=None`` is
        returned with the reasoning.
        """
        country_upper = partner_country_code.upper()
        is_eu = country_upper in self.EU_COUNTRIES

        # Try to find an auto-apply fiscal position matching the country
        auto_fp = await self._find_auto_apply_fiscal_position(country_upper)

        if auto_fp:
            return FiscalPositionSuggestion(
                fiscal_position_id=auto_fp.id,
                fiscal_position_name=auto_fp.name,
                country_code=country_upper,
                is_eu=is_eu,
                reason=f"Auto-apply fiscal position matched for country '{country_upper}'.",
            )

        # No auto-apply match — provide a suggestion based on rules
        if is_eu and vat_number:
            reason = (
                f"EU B2B sale to '{country_upper}' with VAT number '{vat_number}': "
                "reverse charge mechanism applies. Tax liability shifts to the buyer."
            )
            return FiscalPositionSuggestion(
                fiscal_position_id=None,
                fiscal_position_name="Intra-EU B2B (Reverse Charge)",
                country_code=country_upper,
                is_eu=True,
                reason=reason,
            )

        if is_eu and not vat_number:
            reason = (
                f"EU B2C sale to '{country_upper}' without VAT number: "
                "destination country tax rates apply. Consider OSS registration."
            )
            return FiscalPositionSuggestion(
                fiscal_position_id=None,
                fiscal_position_name="Intra-EU B2C (Destination Country Taxes)",
                country_code=country_upper,
                is_eu=True,
                reason=reason,
            )

        # Non-EU
        reason = (
            f"Export sale to non-EU country '{country_upper}': "
            "zero-rated or exempt from domestic VAT."
        )
        return FiscalPositionSuggestion(
            fiscal_position_id=None,
            fiscal_position_name="Export (Tax Exempt)",
            country_code=country_upper,
            is_eu=False,
            reason=reason,
        )

    async def apply_taxes_to_invoice(
        self,
        move_id: uuid.UUID,
        fiscal_position_id: uuid.UUID | None = None,
    ) -> list[InvoiceTaxApplication]:
        """Apply fiscal position tax mappings to all product lines of an invoice.

        For each product line on the invoice, the line's current taxes are mapped
        through the fiscal position, and the tax amounts are recomputed. The
        line's ``tax_ids`` relationship is updated in the database.

        If *fiscal_position_id* is None, the invoice's own ``fiscal_position_id``
        is used.  If neither is set, a ``BusinessRuleError`` is raised.
        """
        move = await self._move_repo.get_by_id(move_id)
        if move is None:
            raise NotFoundError("moves", str(move_id))

        if move.move_type not in INVOICE_TYPES:
            raise BusinessRuleError(
                f"Move '{move.name}' is of type '{move.move_type}', not an invoice."
            )

        if move.state != "draft":
            raise BusinessRuleError(
                f"Cannot modify taxes on a non-draft invoice (state='{move.state}')."
            )

        fp_id = fiscal_position_id or move.fiscal_position_id
        if fp_id is None:
            raise BusinessRuleError(
                "No fiscal position specified and the invoice has none assigned."
            )

        fiscal_position = await self._fiscal_position_repo.get_by_id(fp_id)
        if fiscal_position is None:
            raise NotFoundError("fiscal_positions", str(fp_id))

        # Build source -> dest mapping
        src_to_dest: dict[uuid.UUID, uuid.UUID | None] = {}
        for mapping in fiscal_position.tax_mappings:
            src_to_dest[mapping.tax_src_id] = mapping.tax_dest_id

        # Pre-fetch all destination taxes we will need
        dest_tax_ids = {v for v in src_to_dest.values() if v is not None}
        dest_taxes: dict[uuid.UUID, Tax] = {}
        for tax_id in dest_tax_ids:
            tax = await self._tax_repo.get_by_id(tax_id)
            if tax is not None:
                dest_taxes[tax.id] = tax

        results: list[InvoiceTaxApplication] = []

        # Process only product lines (not tax lines, payment term lines, etc.)
        product_lines = [
            line for line in move.lines if line.display_type == "product"
        ]

        for idx, line in enumerate(product_lines):
            original_tax_ids = [t.id for t in line.tax_ids]
            new_tax_ids: list[uuid.UUID] = []
            mapped_any = False

            for tax_id in original_tax_ids:
                if tax_id in src_to_dest:
                    mapped_any = True
                    dest_id = src_to_dest[tax_id]
                    if dest_id is not None:
                        new_tax_ids.append(dest_id)
                else:
                    new_tax_ids.append(tax_id)

            # Compute tax amount on the line's subtotal
            base_amount = line.price_subtotal
            tax_amount = 0.0
            new_tax_objects: list[Tax] = []

            for tid in new_tax_ids:
                tax = dest_taxes.get(tid)
                if tax is None:
                    tax = await self._tax_repo.get_by_id(tid)
                if tax is not None:
                    tax_amount += tax.compute_amount(base_amount, line.quantity, line.price_unit)
                    new_tax_objects.append(tax)

            # Update the line's tax relationship
            line.tax_ids = new_tax_objects

            reason = ""
            if mapped_any:
                reason = f"Fiscal position '{fiscal_position.name}' applied."
            else:
                reason = "No tax mappings matched; taxes unchanged."

            results.append(InvoiceTaxApplication(
                line_index=idx,
                original_tax_ids=original_tax_ids,
                applied_tax_ids=new_tax_ids,
                tax_amount=round(tax_amount, 2),
                reason=reason,
            ))

        # Update the invoice's fiscal_position_id if it changed
        if move.fiscal_position_id != fp_id:
            move.fiscal_position_id = fp_id

        await self.db.flush()

        await event_bus.publish(
            "invoice.fiscal_position.applied",
            {
                "move_id": str(move_id),
                "fiscal_position_id": str(fp_id),
                "lines_affected": len([r for r in results if r.reason.startswith("Fiscal")]),
            },
        )

        logger.info(
            "Applied fiscal position '%s' to invoice '%s': %d lines processed",
            fiscal_position.name,
            move.name,
            len(results),
        )

        return results

    async def get_oss_info(
        self,
        origin_country: str,
        destination_country: str,
    ) -> OSSInfo:
        """Determine if the EU One-Stop-Shop (OSS) scheme applies.

        OSS applies to B2C cross-border sales within the EU where the seller
        uses the OSS registration to declare VAT in the destination country
        instead of registering for VAT in each member state.

        OSS is only relevant when:
        - Both countries are EU member states
        - The countries are different (cross-border)
        """
        origin = origin_country.upper()
        destination = destination_country.upper()
        origin_is_eu = origin in self.EU_COUNTRIES
        dest_is_eu = destination in self.EU_COUNTRIES

        if not origin_is_eu or not dest_is_eu:
            return OSSInfo(
                is_oss_applicable=False,
                origin_country=origin,
                destination_country=destination,
                explanation=(
                    "OSS is only applicable for intra-EU cross-border sales. "
                    f"Origin '{origin}' is {'EU' if origin_is_eu else 'non-EU'}, "
                    f"destination '{destination}' is {'EU' if dest_is_eu else 'non-EU'}."
                ),
            )

        if origin == destination:
            return OSSInfo(
                is_oss_applicable=False,
                origin_country=origin,
                destination_country=destination,
                explanation="Domestic sale — OSS does not apply when origin and destination are the same country.",
            )

        # Cross-border intra-EU: OSS applies
        # Standard EU VAT rates by country (simplified — common standard rates)
        eu_standard_rates: dict[str, float] = {
            "AT": 20.0, "BE": 21.0, "BG": 20.0, "HR": 25.0, "CY": 19.0,
            "CZ": 21.0, "DK": 25.0, "EE": 22.0, "FI": 24.0, "FR": 20.0,
            "DE": 19.0, "GR": 24.0, "HU": 27.0, "IE": 23.0, "IT": 22.0,
            "LV": 21.0, "LT": 21.0, "LU": 17.0, "MT": 18.0, "NL": 21.0,
            "PL": 23.0, "PT": 23.0, "RO": 19.0, "SK": 20.0, "SI": 22.0,
            "ES": 21.0, "SE": 25.0,
        }

        oss_rate = eu_standard_rates.get(destination)

        return OSSInfo(
            is_oss_applicable=True,
            origin_country=origin,
            destination_country=destination,
            oss_tax_rate=oss_rate,
            explanation=(
                f"OSS applies for B2C sale from '{origin}' to '{destination}'. "
                f"Destination country standard VAT rate: {oss_rate}%. "
                "Seller should charge the destination country VAT rate and declare via OSS."
            ),
        )

    async def auto_apply_fiscal_position(
        self,
        move_id: uuid.UUID,
    ) -> FiscalPositionSuggestion:
        """Auto-detect and apply the appropriate fiscal position to an invoice.

        Reads the invoice's partner country and VAT information to determine the
        correct fiscal position, then applies it to the invoice lines.

        Returns the suggestion that was applied (or the reason none was found).
        """
        move = await self._move_repo.get_by_id(move_id)
        if move is None:
            raise NotFoundError("moves", str(move_id))

        if move.move_type not in INVOICE_TYPES:
            raise BusinessRuleError(
                f"Move '{move.name}' is of type '{move.move_type}', not an invoice."
            )

        if move.state != "draft":
            raise BusinessRuleError(
                f"Cannot auto-apply fiscal position on a non-draft invoice (state='{move.state}')."
            )

        if move.partner_id is None:
            raise BusinessRuleError(
                "Cannot auto-detect fiscal position: invoice has no partner assigned."
            )

        # Load the partner to get country and VAT information
        from src.modules.accounting.models.move import Move as MoveModel  # noqa: avoid circular

        partner = await self.db.get(self._resolve_partner_model(), move.partner_id)
        if partner is None:
            raise NotFoundError("partners", str(move.partner_id))

        country_code = getattr(partner, "country_code", None)
        if not country_code:
            raise BusinessRuleError(
                f"Partner '{getattr(partner, 'name', move.partner_id)}' has no country code set. "
                "Cannot determine fiscal position."
            )

        vat_number = getattr(partner, "vat", None)
        is_company = getattr(partner, "is_company", True)

        suggestion = await self.suggest_fiscal_position(
            partner_country_code=country_code,
            is_company=is_company,
            vat_number=vat_number,
        )

        # If we found a fiscal position, apply it to the invoice
        if suggestion.fiscal_position_id is not None:
            await self.apply_taxes_to_invoice(
                move_id=move_id,
                fiscal_position_id=suggestion.fiscal_position_id,
            )
            logger.info(
                "Auto-applied fiscal position '%s' to invoice '%s'",
                suggestion.fiscal_position_name,
                move.name,
            )
        else:
            # Update the invoice's fiscal_position_id to None (clear any previous)
            move.fiscal_position_id = None
            await self.db.flush()
            logger.info(
                "No fiscal position auto-applied to invoice '%s': %s",
                move.name,
                suggestion.reason,
            )

        await event_bus.publish(
            "invoice.fiscal_position.auto_applied",
            {
                "move_id": str(move_id),
                "fiscal_position_id": str(suggestion.fiscal_position_id) if suggestion.fiscal_position_id else None,
                "reason": suggestion.reason,
            },
        )

        return suggestion

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _find_auto_apply_fiscal_position(
        self,
        country_code: str,
    ) -> FiscalPosition | None:
        """Find an active fiscal position with auto_apply=True for the given country."""
        result = await self.db.execute(
            select(FiscalPosition)
            .where(
                FiscalPosition.is_active.is_(True),
                FiscalPosition.auto_apply.is_(True),
                FiscalPosition.country_code == country_code,
            )
            .order_by(FiscalPosition.sequence)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _resolve_partner_model():
        """Lazily resolve the Partner model to avoid circular imports."""
        from src.core.database.base import Base

        for mapper in Base.registry.mappers:
            if mapper.class_.__tablename__ == "partners":
                return mapper.class_
        raise RuntimeError("Partner model not found in SQLAlchemy registry.")
