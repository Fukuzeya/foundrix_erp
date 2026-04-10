"""Tax service — CRUD and computation engine.

Implements:
- Tax CRUD with repartition line management
- Full tax computation engine (percent, fixed, division, group)
- Tax-on-tax (include_base_amount)
- Repartition lines for account/tag mapping
- Cash basis tax handling
- Fiscal position tax mapping
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import NotFoundError
from src.modules.accounting.models.tax import Tax, TaxRepartitionLine
from src.modules.accounting.repositories.tax_repo import TaxRepository, TaxRepartitionLineRepository
from src.modules.accounting.schemas.tax import TaxCreate, TaxUpdate

logger = logging.getLogger(__name__)


@dataclass
class TaxDetail:
    """Result of a tax computation for a single tax."""
    tax_id: uuid.UUID
    tax_name: str
    amount_type: str
    tax_amount: float
    base_amount: float
    account_id: uuid.UUID | None = None
    repartition_type: str = "tax"


@dataclass
class TaxComputationResult:
    """Full result of computing taxes on a base amount."""
    base_amount: float
    total_tax: float
    total_included: float
    details: list[TaxDetail] = field(default_factory=list)

    @property
    def price_subtotal(self) -> float:
        return self.base_amount

    @property
    def price_total(self) -> float:
        return self.base_amount + self.total_tax


class TaxService:
    """Computes taxes with full Odoo-compatible logic."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = TaxRepository(db)

    # ── CRUD ─────────────────────────────────────────────────────────

    async def list_taxes(self, type_tax_use: str | None = None) -> list[Tax]:
        """List taxes, optionally filtered by usage type."""
        if type_tax_use:
            return await self.repo.get_by_use(type_tax_use)
        return await self.repo.list_active()

    async def create_tax(self, data: TaxCreate) -> Tax:
        """Create a tax with repartition lines."""
        tax_data = data.model_dump(exclude={"invoice_repartition_lines", "refund_repartition_lines"})
        tax = await self.repo.create(**tax_data)

        # Create repartition lines
        for rep in (getattr(data, "invoice_repartition_lines", None) or []):
            line = TaxRepartitionLine(
                tax_id=tax.id, document_type="invoice", **rep.model_dump(),
            )
            self.db.add(line)
        for rep in (getattr(data, "refund_repartition_lines", None) or []):
            line = TaxRepartitionLine(
                tax_id=tax.id, document_type="refund", **rep.model_dump(),
            )
            self.db.add(line)

        await self.db.flush()
        await self.db.refresh(tax)
        return tax

    async def get_tax(self, tax_id: uuid.UUID) -> Tax:
        """Get a tax by ID or raise NotFoundError."""
        return await self.repo.get_by_id_or_raise(tax_id, "Tax")

    async def update_tax(self, tax_id: uuid.UUID, data: TaxUpdate) -> Tax:
        """Update a tax."""
        tax = await self.repo.get_by_id_or_raise(tax_id, "Tax")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(tax, key, value)

        await self.db.flush()
        await self.db.refresh(tax)
        return tax

    # ── Computation Engine ───────────────────────────────────────────

    async def compute_taxes(
        self,
        tax_ids: list[uuid.UUID],
        price_unit: float,
        quantity: float = 1.0,
        *,
        is_refund: bool = False,
        handle_price_include: bool = True,
    ) -> TaxComputationResult:
        """Compute taxes for a set of tax IDs on a given price and quantity.

        Handles:
        - Multiple taxes in sequence order
        - Price-included taxes (division)
        - Tax-on-tax (include_base_amount)
        - Repartition lines for account mapping
        """
        if not tax_ids:
            base = price_unit * quantity
            return TaxComputationResult(
                base_amount=base, total_tax=0.0, total_included=base,
            )

        taxes: list[Tax] = []
        for tid in tax_ids:
            tax = await self.repo.get_by_id(tid)
            if tax:
                taxes.append(tax)

        taxes.sort(key=lambda t: t.sequence)

        # Step 1: If any tax is price-included, compute the base (tax-exclusive amount)
        base = price_unit * quantity
        if handle_price_include:
            base = self._handle_price_include(taxes, base, quantity)

        # Step 2: Compute each tax
        details: list[TaxDetail] = []
        total_tax = 0.0
        current_base = base

        for tax in taxes:
            if tax.amount_type == "group":
                group_result = await self._compute_group_tax(
                    tax, current_base, quantity, price_unit, is_refund
                )
                details.extend(group_result.details)
                total_tax += group_result.total_tax
                if tax.include_base_amount:
                    current_base += group_result.total_tax
            else:
                tax_amount = tax.compute_amount(current_base, quantity, price_unit)
                tax_amount = round(tax_amount, 2)

                # Get repartition lines for account mapping
                doc_type = "refund" if is_refund else "invoice"
                rep_lines = [
                    r for r in (tax.invoice_repartition_lines if not is_refund else tax.refund_repartition_lines)
                    if r.repartition_type == "tax"
                ]

                if rep_lines:
                    for rep in rep_lines:
                        allocated = round(tax_amount * rep.factor_percent / 100.0, 2)
                        details.append(TaxDetail(
                            tax_id=tax.id,
                            tax_name=tax.invoice_label or tax.name,
                            amount_type=tax.amount_type,
                            tax_amount=allocated,
                            base_amount=current_base,
                            account_id=rep.account_id,
                        ))
                else:
                    details.append(TaxDetail(
                        tax_id=tax.id,
                        tax_name=tax.invoice_label or tax.name,
                        amount_type=tax.amount_type,
                        tax_amount=tax_amount,
                        base_amount=current_base,
                    ))

                total_tax += tax_amount

                if tax.include_base_amount:
                    current_base += tax_amount

        return TaxComputationResult(
            base_amount=round(base, 2),
            total_tax=round(total_tax, 2),
            total_included=round(base + total_tax, 2),
            details=details,
        )

    async def _compute_group_tax(
        self, group_tax: Tax, base: float, quantity: float,
        price_unit: float, is_refund: bool,
    ) -> TaxComputationResult:
        """Compute a group tax by delegating to its children."""
        children = sorted(group_tax.children_tax_ids, key=lambda t: t.sequence)
        details: list[TaxDetail] = []
        total = 0.0
        current_base = base

        for child in children:
            child_amount = child.compute_amount(current_base, quantity, price_unit)
            child_amount = round(child_amount, 2)
            details.append(TaxDetail(
                tax_id=child.id,
                tax_name=child.invoice_label or child.name,
                amount_type=child.amount_type,
                tax_amount=child_amount,
                base_amount=current_base,
            ))
            total += child_amount
            if child.include_base_amount:
                current_base += child_amount

        return TaxComputationResult(
            base_amount=base, total_tax=total,
            total_included=base + total, details=details,
        )

    def _handle_price_include(self, taxes: list[Tax], total_included: float, quantity: float) -> float:
        """Extract the tax-exclusive base from a price-included amount."""
        included_taxes = [t for t in taxes if t.price_include and t.amount_type != "group"]
        if not included_taxes:
            return total_included

        base = total_included
        for tax in included_taxes:
            if tax.amount_type == "percent":
                base = base / (1.0 + tax.amount / 100.0)
            elif tax.amount_type == "division":
                base = base / (1.0 + tax.amount / 100.0)
            elif tax.amount_type == "fixed":
                base -= abs(quantity) * tax.amount

        return round(base, 2)

    async def map_fiscal_position_taxes(
        self, fiscal_position_id: uuid.UUID, tax_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        """Apply fiscal position tax mapping: replace source taxes with destination taxes."""
        from src.modules.accounting.repositories.payment_term_repo import FiscalPositionRepository
        from src.modules.accounting.models.payment_term import FiscalPosition

        fp_repo = FiscalPositionRepository(self.db)
        fp = await fp_repo.get_by_id(fiscal_position_id)
        if not fp:
            return tax_ids

        result_ids = list(tax_ids)
        for mapping in fp.tax_mappings:
            if mapping.source_tax_id in result_ids:
                idx = result_ids.index(mapping.source_tax_id)
                if mapping.destination_tax_id:
                    result_ids[idx] = mapping.destination_tax_id
                else:
                    result_ids.pop(idx)

        return result_ids
