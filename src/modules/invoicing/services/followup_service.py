"""Follow-up service — manages payment follow-up levels and partner follow-up processing.

Handles:
- Follow-up level CRUD (escalation steps configuration)
- Determining the correct follow-up level for overdue partners
- Processing follow-ups (advancing levels, recording actions)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.invoicing.models.followup import FollowUpLevel, PartnerFollowUp
from src.modules.invoicing.repositories.followup_repo import (
    FollowUpLevelRepository,
    PartnerFollowUpRepository,
)
from src.modules.invoicing.schemas.followup import (
    FollowUpLevelCreate,
    FollowUpLevelUpdate,
    PartnerFollowUpUpdate,
    FollowUpAction,
)

logger = logging.getLogger(__name__)


class FollowUpService:
    """Manages payment follow-up levels and partner follow-up processing."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.level_repo = FollowUpLevelRepository(db)
        self.partner_repo = PartnerFollowUpRepository(db)

    # ── Follow-Up Level CRUD ──────────────────────────────────────────

    async def get_level(self, level_id: uuid.UUID) -> FollowUpLevel:
        """Get a follow-up level by ID."""
        level = await self.level_repo.get_by_id(level_id)
        if not level:
            raise NotFoundError("FollowUpLevel", str(level_id))
        return level

    async def list_levels(self) -> list[FollowUpLevel]:
        """List all active follow-up levels ordered by delay days."""
        return await self.level_repo.list_ordered()

    async def create_level(self, data: FollowUpLevelCreate) -> FollowUpLevel:
        """Create a new follow-up level."""
        level = FollowUpLevel(
            name=data.name,
            sequence=data.sequence,
            delay_days=data.delay_days,
            action=data.action,
            send_email=data.send_email,
            send_letter=data.send_letter,
            join_invoices=data.join_invoices,
            manual_action=data.manual_action,
            manual_action_note=data.manual_action_note,
            email_subject=data.email_subject,
            email_body=data.email_body,
            is_active=data.is_active,
        )
        self.db.add(level)
        await self.db.flush()
        await self.db.refresh(level)
        return level

    async def update_level(
        self, level_id: uuid.UUID, data: FollowUpLevelUpdate,
    ) -> FollowUpLevel:
        """Update a follow-up level."""
        level = await self.level_repo.get_by_id(level_id)
        if not level:
            raise NotFoundError("FollowUpLevel", str(level_id))

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(level, key, value)

        await self.db.flush()
        await self.db.refresh(level)
        return level

    # ── Partner Follow-Up ─────────────────────────────────────────────

    async def get_partner_followup(self, partner_id: uuid.UUID) -> PartnerFollowUp:
        """Get or create the follow-up record for a partner."""
        return await self.partner_repo.get_or_create(partner_id)

    async def update_partner_followup(
        self, partner_id: uuid.UUID, data: PartnerFollowUpUpdate,
    ) -> PartnerFollowUp:
        """Update a partner's follow-up settings (e.g., block, set note)."""
        followup = await self.partner_repo.get_or_create(partner_id)

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(followup, key, value)

        await self.db.flush()
        await self.db.refresh(followup)
        return followup

    # ── Follow-Up Processing ──────────────────────────────────────────

    async def process_followups(
        self,
        as_of: date | None = None,
        *,
        partner_ids: list[uuid.UUID] | None = None,
    ) -> list[FollowUpAction]:
        """Process follow-ups for all partners (or specific ones) with overdue invoices.

        For each partner:
        1. Determine overdue days from their oldest unpaid invoice
        2. Find the matching follow-up level
        3. If the level has advanced, record the action
        4. Schedule the next follow-up date

        Returns a list of FollowUpAction results.
        """
        target = as_of or date.today()
        levels = await self.level_repo.list_ordered()

        if not levels:
            logger.warning("No follow-up levels configured; skipping processing")
            return []

        # Get due follow-ups
        if partner_ids:
            due_followups = []
            for pid in partner_ids:
                fu = await self.partner_repo.get_or_create(pid)
                if not fu.blocked:
                    due_followups.append(fu)
        else:
            due_followups = await self.partner_repo.get_due_followups(target)

        results = []
        for followup in due_followups:
            try:
                action = await self._process_single_followup(
                    followup, levels, target,
                )
                if action:
                    results.append(action)
            except Exception:
                logger.exception(
                    "Failed to process follow-up for partner %s",
                    followup.partner_id,
                )

        await self.db.flush()
        return results

    async def _process_single_followup(
        self,
        followup: PartnerFollowUp,
        levels: list[FollowUpLevel],
        target: date,
    ) -> FollowUpAction | None:
        """Process follow-up for a single partner.

        This is a simplified implementation that advances the partner
        to the next follow-up level based on configured levels.
        In a full implementation, this would query actual overdue invoices
        and compute overdue amounts.
        """
        # Determine next level
        if followup.current_level_id is None:
            # First follow-up — use the first level
            next_level = levels[0] if levels else None
        else:
            # Find the next level after current
            current_idx = None
            for i, level in enumerate(levels):
                if level.id == followup.current_level_id:
                    current_idx = i
                    break

            if current_idx is not None and current_idx + 1 < len(levels):
                next_level = levels[current_idx + 1]
            else:
                # Already at highest level — re-send last level
                next_level = levels[-1] if levels else None

        if not next_level:
            return None

        # Update partner follow-up record
        followup.last_followup_level_id = followup.current_level_id
        followup.current_level_id = next_level.id
        followup.last_followup_date = target
        followup.next_action_date = target + timedelta(days=next_level.delay_days)

        action = FollowUpAction(
            partner_id=followup.partner_id,
            level_name=next_level.name,
            action=next_level.action.value if hasattr(next_level.action, 'value') else next_level.action,
            overdue_amount=0.0,  # would be computed from actual invoices
            overdue_invoice_count=0,  # would be computed from actual invoices
            next_action_date=followup.next_action_date,
        )

        await event_bus.publish("followup.action_taken", {
            "partner_id": str(followup.partner_id),
            "level": next_level.name,
            "action": action.action,
        })

        return action
