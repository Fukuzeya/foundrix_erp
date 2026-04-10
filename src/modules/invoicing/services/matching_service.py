"""3-Way Matching Service — matches vendor bills against POs and receipts.

Implements two-way (PO vs Bill) and three-way (PO vs Receipt vs Bill) matching
with configurable tolerance thresholds. Exceptions require manual override.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.core.events import event_bus
from src.modules.accounting.models.move import Move
from src.modules.accounting.repositories.move_repo import MoveRepository
from src.modules.invoicing.models.matching import (
    BillMatch,
    MatchingRule,
    PurchaseOrderReference,
    ReceiptReference,
)
from src.modules.invoicing.repositories.matching_repo import (
    BillMatchRepository,
    PurchaseOrderRepository,
    ReceiptRepository,
)
from src.modules.invoicing.schemas.matching import MatchResult, MatchingSummary

logger = logging.getLogger(__name__)


class ThreeWayMatchingService:
    """Orchestrates 3-way matching between purchase orders, receipts, and vendor bills."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_repo = MoveRepository(db)
        self.po_repo = PurchaseOrderRepository(db)
        self.receipt_repo = ReceiptRepository(db)
        self.match_repo = BillMatchRepository(db)

    # ── Public API ───────────────────────────────────────────────────

    async def match_bill(
        self,
        bill_id: uuid.UUID,
        po_id: uuid.UUID | None = None,
        receipt_id: uuid.UUID | None = None,
    ) -> MatchResult:
        """Match a vendor bill against a purchase order and/or receipt.

        If both po_id and receipt_id are provided, performs a 3-way match.
        If only po_id is provided, performs a 2-way match.
        """
        # Fetch and validate the bill
        bill = await self.move_repo.get_by_id_or_raise(bill_id, "vendor_bill")
        if bill.move_type != "in_invoice":
            raise BusinessRuleError("Only vendor bills (in_invoice) can be matched.")

        # Check for existing match
        existing = await self.match_repo.get_by_bill(bill_id)
        if existing and existing.match_status in ("matched", "overridden"):
            raise ConflictError(
                f"Bill {bill_id} already has an active match "
                f"(status: {existing.match_status})."
            )

        if po_id is None and receipt_id is None:
            raise ValidationError("At least one of po_id or receipt_id must be provided.")

        # Fetch PO and receipt
        po: PurchaseOrderReference | None = None
        receipt: ReceiptReference | None = None

        if po_id:
            po = await self.po_repo.get_by_id_or_raise(po_id, "purchase_order")
        if receipt_id:
            receipt = await self.receipt_repo.get_by_id_or_raise(receipt_id, "receipt")

        # Determine match type and compute variance
        bill_amount = bill.amount_total
        if po and receipt:
            match_type = "three_way"
            variance_amount, variance_percent, details = self._compute_three_way_match(
                bill_amount, po, receipt,
            )
        elif po:
            match_type = "two_way"
            variance_amount, variance_percent, details = self._compute_two_way_match(
                bill_amount, po,
            )
        else:
            raise ValidationError(
                "A purchase order is required for matching. "
                "Provide po_id to perform a 2-way or 3-way match."
            )

        # Get active matching rule for tolerance check
        rule = await self._get_active_rule()
        within_tolerance = self._check_tolerance(variance_amount, variance_percent, rule)

        # Determine match status
        if within_tolerance and rule and rule.auto_validate:
            match_status = "matched"
        elif within_tolerance:
            match_status = "pending"
        else:
            match_status = "exception"
            details.append(
                f"Variance exceeds tolerance: amount={variance_amount:.2f}, "
                f"percent={variance_percent:.2f}%"
            )

        # Calculate amounts for the match record
        po_amount = po.total_amount if po else None
        receipt_amount: float | None = None
        if receipt:
            receipt_amount = sum(
                line.quantity_received * (line.po_line.price_unit if line.po_line else 0.0)
                for line in receipt.lines
            )

        # Create or update match record
        if existing:
            await self.match_repo.update(
                existing.id,
                po_id=po_id,
                receipt_id=receipt_id,
                match_type=match_type,
                match_status=match_status,
                po_amount=po_amount,
                receipt_amount=receipt_amount,
                bill_amount=bill_amount,
                variance_amount=variance_amount,
                variance_percent=variance_percent,
                matched_at=datetime.utcnow() if match_status == "matched" else None,
                exception_reason="; ".join(details) if match_status == "exception" else None,
            )
        else:
            await self.match_repo.create(
                bill_id=bill_id,
                po_id=po_id,
                receipt_id=receipt_id,
                match_type=match_type,
                match_status=match_status,
                po_amount=po_amount,
                receipt_amount=receipt_amount,
                bill_amount=bill_amount,
                variance_amount=variance_amount,
                variance_percent=variance_percent,
                matched_at=datetime.utcnow() if match_status == "matched" else None,
                exception_reason="; ".join(details) if match_status == "exception" else None,
            )

        # Publish events
        event_data = {
            "bill_id": str(bill_id),
            "po_id": str(po_id) if po_id else None,
            "receipt_id": str(receipt_id) if receipt_id else None,
            "match_type": match_type,
            "match_status": match_status,
            "variance_amount": variance_amount,
        }
        if match_status == "matched":
            await event_bus.publish("bill_match.matched", event_data)
        elif match_status == "exception":
            await event_bus.publish("bill_match.exception", event_data)

        logger.info(
            "Bill %s matched (type=%s, status=%s, variance=%.2f)",
            bill_id, match_type, match_status, variance_amount,
        )

        return MatchResult(
            bill_id=bill_id,
            po_id=po_id,
            receipt_id=receipt_id,
            match_status=match_status,
            match_type=match_type,
            variance_amount=variance_amount,
            variance_percent=variance_percent,
            details=details,
        )

    async def auto_match_bill(self, bill_id: uuid.UUID) -> MatchResult:
        """Attempt to automatically find and match a PO for a vendor bill.

        Searches by the bill's ``ref`` field (vendor reference / PO number)
        and falls back to matching by partner_id.
        """
        bill = await self.move_repo.get_by_id_or_raise(bill_id, "vendor_bill")
        if bill.move_type != "in_invoice":
            raise BusinessRuleError("Only vendor bills (in_invoice) can be auto-matched.")

        po: PurchaseOrderReference | None = None
        receipt: ReceiptReference | None = None

        # Strategy 1: Match by ref field (often contains PO number)
        if bill.ref:
            po = await self.po_repo.find_by_po_number(bill.ref.strip())

        # Strategy 2: Fall back to partner-based lookup (most recent unmatched PO)
        if po is None and bill.partner_id:
            partner_pos = await self.po_repo.list_by_partner(
                bill.partner_id, limit=1,
            )
            # Find first PO that is not already fully billed
            for candidate in partner_pos:
                if candidate.state not in ("billed", "done"):
                    po = candidate
                    break

        if po is None:
            raise NotFoundError(
                "purchase_order",
                f"auto-match for bill {bill_id}",
            )

        # Try to find a receipt for 3-way match
        receipts = await self.receipt_repo.list_by_po(po.id, limit=1)
        if receipts:
            receipt = receipts[0]

        return await self.match_bill(
            bill_id,
            po_id=po.id,
            receipt_id=receipt.id if receipt else None,
        )

    async def validate_match(self, match_id: uuid.UUID) -> BillMatch:
        """Approve a pending match, transitioning it to 'matched' status."""
        match = await self.match_repo.get_by_id_or_raise(match_id, "bill_match")

        if match.match_status != "pending":
            raise BusinessRuleError(
                f"Only pending matches can be validated. "
                f"Current status: {match.match_status}"
            )

        updated = await self.match_repo.update(
            match_id,
            match_status="matched",
            matched_at=datetime.utcnow(),
        )

        await event_bus.publish("bill_match.matched", {
            "bill_id": str(match.bill_id),
            "po_id": str(match.po_id) if match.po_id else None,
            "match_id": str(match_id),
            "match_type": match.match_type,
            "match_status": "matched",
        })

        logger.info("Match %s validated (bill=%s)", match_id, match.bill_id)
        return updated

    async def override_exception(
        self,
        match_id: uuid.UUID,
        reason: str,
        user_id: uuid.UUID,
    ) -> BillMatch:
        """Override an exception match with a documented reason."""
        match = await self.match_repo.get_by_id_or_raise(match_id, "bill_match")

        if match.match_status != "exception":
            raise BusinessRuleError(
                f"Only exception matches can be overridden. "
                f"Current status: {match.match_status}"
            )

        if not reason or not reason.strip():
            raise ValidationError("A reason is required to override an exception.")

        updated = await self.match_repo.update(
            match_id,
            match_status="overridden",
            exception_reason=reason.strip(),
            matched_by=user_id,
            matched_at=datetime.utcnow(),
        )

        await event_bus.publish("bill_match.overridden", {
            "bill_id": str(match.bill_id),
            "po_id": str(match.po_id) if match.po_id else None,
            "match_id": str(match_id),
            "overridden_by": str(user_id),
            "reason": reason.strip(),
        })

        logger.info(
            "Match %s exception overridden by user %s (reason: %s)",
            match_id, user_id, reason.strip(),
        )
        return updated

    async def get_match_status(self, bill_id: uuid.UUID) -> BillMatch | None:
        """Get the current match record for a bill."""
        return await self.match_repo.get_by_bill(bill_id)

    async def get_unmatched_bills(
        self,
        partner_id: uuid.UUID | None = None,
    ) -> list[Move]:
        """List vendor bills that do not have a match record."""
        # Get all bill_ids that already have matches
        matched_subquery = select(BillMatch.bill_id)

        query = select(Move).where(
            Move.move_type == "in_invoice",
            Move.state == "posted",
            Move.id.notin_(matched_subquery),
        )
        if partner_id:
            query = query.where(Move.partner_id == partner_id)

        query = query.order_by(Move.date.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_matching_exceptions(self) -> list[BillMatch]:
        """List all matches with exception status."""
        return await self.match_repo.list_exceptions()

    async def get_matching_summary(self) -> MatchingSummary:
        """Get aggregate counts of match statuses."""
        counts = await self.match_repo.get_summary_counts()
        return MatchingSummary(**counts)

    # ── Private Helpers ──────────────────────────────────────────────

    def _compute_two_way_match(
        self,
        bill_amount: float,
        po: PurchaseOrderReference,
    ) -> tuple[float, float, list[str]]:
        """Compare bill amount against PO total.

        Returns (variance_amount, variance_percent, details).
        """
        details: list[str] = []
        po_amount = po.total_amount

        variance_amount = abs(bill_amount - po_amount)
        variance_percent = (
            (variance_amount / po_amount * 100.0) if po_amount != 0 else 0.0
        )

        details.append(f"PO amount: {po_amount:.2f}, Bill amount: {bill_amount:.2f}")

        if variance_amount > 0:
            details.append(
                f"Amount variance: {variance_amount:.2f} ({variance_percent:.2f}%)"
            )

        # Check line-level quantity discrepancies
        for line in po.lines:
            if line.quantity_billed > line.quantity_ordered:
                details.append(
                    f"Line '{line.description}': billed qty ({line.quantity_billed}) "
                    f"exceeds ordered qty ({line.quantity_ordered})"
                )

        return variance_amount, variance_percent, details

    def _compute_three_way_match(
        self,
        bill_amount: float,
        po: PurchaseOrderReference,
        receipt: ReceiptReference,
    ) -> tuple[float, float, list[str]]:
        """Compare bill against both PO and receipt.

        Checks amount variance (bill vs PO) and quantity variance
        (received vs ordered). Returns (variance_amount, variance_percent, details).
        """
        # Start with two-way match computation
        variance_amount, variance_percent, details = self._compute_two_way_match(
            bill_amount, po,
        )

        # Additionally check received quantities against ordered
        receipt_amount = 0.0
        for receipt_line in receipt.lines:
            if receipt_line.po_line:
                po_line = receipt_line.po_line
                receipt_amount += receipt_line.quantity_received * po_line.price_unit

                qty_diff = receipt_line.quantity_received - po_line.quantity_ordered
                if abs(qty_diff) > 0.001:
                    details.append(
                        f"Line '{po_line.description}': received {receipt_line.quantity_received} "
                        f"vs ordered {po_line.quantity_ordered} "
                        f"(diff: {qty_diff:+.2f})"
                    )

        # Check receipt amount vs bill amount
        receipt_bill_variance = abs(bill_amount - receipt_amount)
        if receipt_amount > 0 and receipt_bill_variance > 0.01:
            receipt_variance_pct = receipt_bill_variance / receipt_amount * 100.0
            details.append(
                f"Receipt amount: {receipt_amount:.2f}, Bill amount: {bill_amount:.2f} "
                f"(variance: {receipt_bill_variance:.2f} / {receipt_variance_pct:.2f}%)"
            )
            # Use the larger variance for the final result
            if receipt_bill_variance > variance_amount:
                variance_amount = receipt_bill_variance
                variance_percent = receipt_variance_pct

        return variance_amount, variance_percent, details

    def _check_tolerance(
        self,
        variance_amount: float,
        variance_percent: float,
        rule: MatchingRule | None,
    ) -> bool:
        """Check whether the variance falls within the configured tolerance.

        Returns True if within tolerance, False otherwise.
        If no rule is configured, any non-zero variance is out of tolerance.
        """
        if rule is None:
            return variance_amount < 0.01

        # Both tolerance checks must pass (if configured)
        if rule.tolerance_amount > 0 and variance_amount > rule.tolerance_amount:
            return False
        if rule.tolerance_percent > 0 and variance_percent > rule.tolerance_percent:
            return False

        return True

    async def _get_active_rule(self) -> MatchingRule | None:
        """Fetch the first active matching rule."""
        result = await self.db.execute(
            select(MatchingRule)
            .where(MatchingRule.is_active.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none()
