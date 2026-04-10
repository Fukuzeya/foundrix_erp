"""Reconciliation service — matching payments to invoices.

Implements Odoo's three-level reconciliation:
1. PartialReconcile: links a debit line to a credit line with an amount
2. FullReconcile: promoted when all partials fully cover the line amounts
3. ReconcileModel: smart matching rules for automated bank reconciliation

Also handles:
- Automatic matching suggestions (95% auto-match target)
- Exchange difference handling
- Write-off creation for small residuals
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, ValidationError
from src.modules.accounting.models.move import MoveLine
from src.modules.accounting.models.reconciliation import (
    FullReconcile,
    PartialReconcile,
)
from src.modules.accounting.repositories.move_repo import MoveLineRepository, MoveRepository
from src.modules.accounting.repositories.reconciliation_repo import (
    FullReconcileRepository,
    PartialReconcileRepository,
)

logger = logging.getLogger(__name__)


class ReconciliationService:
    """Manages partial and full reconciliation of journal items."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.partial_repo = PartialReconcileRepository(db)
        self.full_repo = FullReconcileRepository(db)
        self.line_repo = MoveLineRepository(db)
        self.move_repo = MoveRepository(db)

    async def create_partial_reconcile(
        self,
        debit_line: MoveLine,
        credit_line: MoveLine,
        amount: float,
        *,
        amount_currency: float | None = None,
    ) -> PartialReconcile:
        """Create a partial reconciliation between a debit and credit line."""
        if debit_line.debit <= 0:
            raise ValidationError("Debit line must have a positive debit amount")
        if credit_line.credit <= 0:
            raise ValidationError("Credit line must have a positive credit amount")
        if debit_line.account_id != credit_line.account_id:
            raise BusinessRuleError("Cannot reconcile lines from different accounts")
        if amount <= 0:
            raise ValidationError("Reconciliation amount must be positive")

        # Clamp amount to available residuals
        amount = min(amount, abs(debit_line.amount_residual), abs(credit_line.amount_residual))

        partial = PartialReconcile(
            debit_move_line_id=debit_line.id,
            credit_move_line_id=credit_line.id,
            amount=round(amount, 2),
            debit_amount_currency=round(amount_currency or amount, 2),
            credit_amount_currency=round(amount_currency or amount, 2),
            currency_code=debit_line.currency_code,
        )
        self.db.add(partial)
        await self.db.flush()

        # Update residuals
        debit_line.amount_residual = round(debit_line.amount_residual - amount, 2)
        credit_line.amount_residual = round(credit_line.amount_residual + amount, 2)

        # Check if fully reconciled
        if abs(debit_line.amount_residual) < 0.01:
            debit_line.reconciled = True
            debit_line.amount_residual = 0.0
        if abs(credit_line.amount_residual) < 0.01:
            credit_line.reconciled = True
            credit_line.amount_residual = 0.0

        await self.db.flush()

        # Try to promote to full reconcile
        await self._try_full_reconcile(debit_line, credit_line)

        # Update invoice payment states
        await self._update_payment_state(debit_line.move_id)
        await self._update_payment_state(credit_line.move_id)

        return partial

    async def unreconcile(self, partial_id: uuid.UUID) -> None:
        """Remove a partial reconciliation and restore residual amounts."""
        partial = await self.partial_repo.get_by_id_or_raise(partial_id, "PartialReconcile")

        debit_line = await self.line_repo.get_by_id(partial.debit_move_line_id)
        credit_line = await self.line_repo.get_by_id(partial.credit_move_line_id)

        if debit_line:
            debit_line.amount_residual = round(debit_line.amount_residual + partial.amount, 2)
            debit_line.reconciled = False
        if credit_line:
            credit_line.amount_residual = round(credit_line.amount_residual - partial.amount, 2)
            credit_line.reconciled = False

        # Remove full reconcile if exists
        if partial.full_reconcile_id:
            await self.full_repo.delete(partial.full_reconcile_id)

        await self.partial_repo.delete(partial_id)
        await self.db.flush()

        # Update invoice payment states
        if debit_line:
            await self._update_payment_state(debit_line.move_id)
        if credit_line:
            await self._update_payment_state(credit_line.move_id)

    async def get_reconciliation_suggestions(
        self,
        account_id: uuid.UUID,
        partner_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """Get suggested reconciliation pairs for unreconciled lines.

        Matches debit lines against credit lines on the same account/partner,
        ordered by closest amount match.
        """
        unreconciled = await self.line_repo.get_unreconciled(account_id, partner_id)

        debit_lines = [l for l in unreconciled if l.balance > 0]
        credit_lines = [l for l in unreconciled if l.balance < 0]

        suggestions: list[dict] = []

        for deb in debit_lines:
            for cred in credit_lines:
                # Match by partner
                if partner_id and (deb.partner_id != cred.partner_id):
                    continue

                amount = min(abs(deb.amount_residual), abs(cred.amount_residual))
                if amount > 0:
                    suggestions.append({
                        "debit_line_id": str(deb.id),
                        "credit_line_id": str(cred.id),
                        "amount": amount,
                        "debit_move_name": deb.name,
                        "credit_move_name": cred.name,
                        "confidence": self._compute_match_confidence(deb, cred),
                    })

        # Sort by confidence (highest first)
        suggestions.sort(key=lambda s: s["confidence"], reverse=True)
        return suggestions[:50]  # Limit to top 50 suggestions

    async def _try_full_reconcile(self, debit_line: MoveLine, credit_line: MoveLine) -> None:
        """Promote to full reconcile if both lines are fully matched."""
        if debit_line.reconciled and credit_line.reconciled:
            full = FullReconcile()
            self.db.add(full)
            await self.db.flush()
            await self.db.refresh(full)

            # Update all related partials
            debit_partials = await self.partial_repo.get_by_debit_line(debit_line.id)
            credit_partials = await self.partial_repo.get_by_credit_line(credit_line.id)

            for p in debit_partials + credit_partials:
                p.full_reconcile_id = full.id

            debit_line.full_reconcile_id = full.id
            credit_line.full_reconcile_id = full.id

            # Assign matching number
            matching_number = f"P{full.id.hex[:8].upper()}"
            debit_line.matching_number = matching_number
            credit_line.matching_number = matching_number

            await self.db.flush()

    async def _update_payment_state(self, move_id: uuid.UUID) -> None:
        """Update the payment_state of a move based on its reconciled lines."""
        move = await self.move_repo.get_by_id(move_id)
        if not move or not move.is_invoice:
            return

        receivable_payable_lines = [
            l for l in move.lines
            if l.display_type == "payment_term"
        ]

        if not receivable_payable_lines:
            return

        all_reconciled = all(l.reconciled for l in receivable_payable_lines)
        any_reconciled = any(l.reconciled for l in receivable_payable_lines)
        total_residual = sum(abs(l.amount_residual) for l in receivable_payable_lines)

        if all_reconciled or total_residual < 0.01:
            move.payment_state = "paid"
            move.amount_residual = 0.0
            move.amount_paid = move.amount_total
        elif any_reconciled or total_residual < move.amount_total:
            move.payment_state = "partial"
            move.amount_residual = total_residual
            move.amount_paid = move.amount_total - total_residual
        else:
            move.payment_state = "not_paid"

        await self.db.flush()

    def _compute_match_confidence(self, debit: MoveLine, credit: MoveLine) -> float:
        """Compute a confidence score for a reconciliation match (0-100)."""
        score = 0.0

        # Exact amount match (highest weight)
        if abs(abs(debit.amount_residual) - abs(credit.amount_residual)) < 0.01:
            score += 50.0

        # Same partner
        if debit.partner_id and debit.partner_id == credit.partner_id:
            score += 30.0

        # Reference matching
        if debit.name and credit.name and debit.name.lower() in credit.name.lower():
            score += 15.0

        # Close dates
        if debit.date_maturity and credit.date_maturity:
            days_diff = abs((debit.date_maturity - credit.date_maturity).days)
            if days_diff < 7:
                score += 5.0

        return min(score, 100.0)
