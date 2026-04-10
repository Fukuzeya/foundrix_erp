"""Credit control service — manages partner credit limits and checks.

Handles:
- Credit control record CRUD
- Credit limit checks before invoice creation
- On-hold management
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.invoicing.models.credit_control import CreditControl
from src.modules.invoicing.repositories.credit_control_repo import CreditControlRepository
from src.modules.invoicing.schemas.credit_control import (
    CreditControlCreate,
    CreditControlUpdate,
    CreditCheckResult,
)

logger = logging.getLogger(__name__)


class CreditControlService:
    """Manages partner credit limits and performs credit checks."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CreditControlRepository(db)

    # ── CRUD ──────────────────────────────────────────────────────────

    async def get_credit_control(self, partner_id: uuid.UUID) -> CreditControl:
        """Get credit control record for a partner (creates if missing)."""
        return await self.repo.get_or_create(partner_id)

    async def create_credit_control(self, data: CreditControlCreate) -> CreditControl:
        """Create a credit control record for a partner."""
        existing = await self.repo.get_by_partner(data.partner_id)
        if existing:
            raise BusinessRuleError(
                f"Credit control record already exists for partner {data.partner_id}"
            )

        control = CreditControl(
            partner_id=data.partner_id,
            credit_limit=data.credit_limit,
            on_hold=data.on_hold,
            warning_threshold=data.warning_threshold,
            note=data.note,
        )
        self.db.add(control)
        await self.db.flush()
        await self.db.refresh(control)

        await event_bus.publish("credit_control.created", {
            "partner_id": str(data.partner_id),
            "credit_limit": data.credit_limit,
        })

        return control

    async def update_credit_control(
        self, partner_id: uuid.UUID, data: CreditControlUpdate,
    ) -> CreditControl:
        """Update credit control settings for a partner."""
        control = await self.repo.get_by_partner(partner_id)
        if not control:
            raise NotFoundError("CreditControl", str(partner_id))

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(control, key, value)

        await self.db.flush()
        await self.db.refresh(control)

        await event_bus.publish("credit_control.updated", {
            "partner_id": str(partner_id),
        })

        return control

    async def set_on_hold(self, partner_id: uuid.UUID, *, on_hold: bool, note: str | None = None) -> CreditControl:
        """Set or clear the on-hold flag for a partner."""
        control = await self.repo.get_or_create(partner_id)
        control.on_hold = on_hold
        if note is not None:
            control.note = note

        await self.db.flush()

        await event_bus.publish("credit_control.hold_changed", {
            "partner_id": str(partner_id),
            "on_hold": on_hold,
        })

        return control

    async def list_on_hold_partners(self) -> list[CreditControl]:
        """List all partners currently on credit hold."""
        return await self.repo.get_on_hold_partners()

    # ── Credit Check ──────────────────────────────────────────────────

    async def check_credit(
        self,
        partner_id: uuid.UUID,
        *,
        additional_amount: float = 0.0,
    ) -> CreditCheckResult:
        """Check a partner's credit status.

        Args:
            partner_id: The partner to check.
            additional_amount: An extra amount to include (e.g., a new invoice
                being created) on top of existing outstanding.

        Returns:
            CreditCheckResult with status: "ok", "warning", "exceeded", or "on_hold".
        """
        control = await self.repo.get_or_create(partner_id)

        if control.on_hold:
            return CreditCheckResult(
                partner_id=partner_id,
                credit_limit=control.credit_limit,
                current_outstanding=additional_amount,
                available_credit=0.0,
                usage_percent=1.0,
                on_hold=True,
                status="on_hold",
            )

        # credit_limit of 0 means unlimited
        if control.credit_limit == 0:
            return CreditCheckResult(
                partner_id=partner_id,
                credit_limit=0.0,
                current_outstanding=additional_amount,
                available_credit=float("inf"),
                usage_percent=0.0,
                on_hold=False,
                status="ok",
            )

        # In a full implementation, query outstanding invoices for this partner.
        # For now, we check against the additional_amount only.
        current_outstanding = await self._get_outstanding_amount(partner_id)
        total_outstanding = current_outstanding + additional_amount
        available = max(control.credit_limit - total_outstanding, 0.0)
        usage = total_outstanding / control.credit_limit if control.credit_limit > 0 else 0.0

        if total_outstanding > control.credit_limit:
            status = "exceeded"
        elif usage >= control.warning_threshold:
            status = "warning"
        else:
            status = "ok"

        return CreditCheckResult(
            partner_id=partner_id,
            credit_limit=control.credit_limit,
            current_outstanding=total_outstanding,
            available_credit=available,
            usage_percent=round(usage, 4),
            on_hold=False,
            status=status,
        )

    async def enforce_credit_check(
        self,
        partner_id: uuid.UUID,
        amount: float,
    ) -> CreditCheckResult:
        """Check credit and raise BusinessRuleError if exceeded or on hold.

        Use this before creating invoices to enforce credit limits.
        """
        result = await self.check_credit(partner_id, additional_amount=amount)

        if result.status == "on_hold":
            raise BusinessRuleError(
                f"Partner {partner_id} is on credit hold. Cannot create invoice."
            )

        if result.status == "exceeded":
            raise BusinessRuleError(
                f"Credit limit exceeded for partner {partner_id}. "
                f"Limit: {result.credit_limit:.2f}, "
                f"Outstanding: {result.current_outstanding:.2f}"
            )

        return result

    # ── Helpers ───────────────────────────────────────────────────────

    async def _get_outstanding_amount(self, partner_id: uuid.UUID) -> float:
        """Get total outstanding amount for a partner from posted invoices.

        In a full implementation, this would query Move records where
        partner_id matches, state='posted', and sum amount_residual.
        """
        from src.modules.accounting.repositories.move_repo import MoveRepository

        move_repo = MoveRepository(self.db)
        outstanding = await move_repo.get_partner_outstanding(partner_id)
        return outstanding if outstanding else 0.0
