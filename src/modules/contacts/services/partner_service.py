"""Partner service — business logic for contacts management.

Implements Odoo-inspired patterns:
- Commercial partner resolution (billing entity hierarchy)
- Display name computation (Company, Person)
- Commercial field syncing (VAT propagates up/down hierarchy)
- Address resolution (find best invoice/delivery address)
- Duplicate detection (same VAT warning)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.core.events import event_bus
from src.modules.contacts.models.partner import Partner
from src.modules.contacts.repositories.partner_repo import PartnerRepository
from src.modules.contacts.schemas.partner import PartnerCreate, PartnerUpdate, PartnerFilter

logger = logging.getLogger(__name__)

# Fields that sync from commercial partner to descendants
COMMERCIAL_FIELDS = ("vat", "company_registry", "industry_id")


class PartnerService:
    """Orchestrates partner CRUD with business rules."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PartnerRepository(db)

    # ── Create ────────────────────────────────────────────────────────

    async def create_partner(self, data: PartnerCreate) -> Partner:
        """Create a new partner with full business rule enforcement."""
        # Validate parent exists if specified
        parent = None
        if data.parent_id:
            parent = await self.repo.get_by_id(data.parent_id)
            if not parent:
                raise NotFoundError("Partner", str(data.parent_id))

        # Duplicate VAT detection
        if data.vat:
            existing = await self.repo.find_by_vat(data.vat)
            if existing:
                raise ConflictError(
                    f"Another partner already has VAT '{data.vat}': {existing.name}"
                )

        # Duplicate ref detection
        if data.ref:
            existing = await self.repo.find_by_ref(data.ref)
            if existing:
                raise ConflictError(
                    f"Another partner already has reference '{data.ref}': {existing.name}"
                )

        # Build kwargs, excluding None values
        kwargs = data.model_dump(exclude_none=True)

        partner = await self.repo.create(**kwargs)

        # Compute display_name and commercial_partner_id
        partner.display_name = self._compute_display_name(partner, parent)
        partner.commercial_partner_id = self._resolve_commercial_partner_id(partner, parent)
        await self.db.flush()

        # Sync commercial fields from parent company if applicable
        if parent and parent.is_company:
            await self._sync_commercial_from_parent(partner, parent)

        await event_bus.publish("partner.created", {
            "partner_id": str(partner.id),
            "name": partner.name,
            "is_company": partner.is_company,
        })

        return partner

    # ── Read ──────────────────────────────────────────────────────────

    async def get_partner(self, partner_id: uuid.UUID) -> Partner:
        return await self.repo.get_by_id_or_raise(partner_id, "Partner")

    async def get_partner_by_email(self, email: str) -> Partner | None:
        return await self.repo.find_by_email(email)

    # ── Update ────────────────────────────────────────────────────────

    async def update_partner(
        self, partner_id: uuid.UUID, data: PartnerUpdate
    ) -> Partner:
        """Update a partner with business rule enforcement."""
        partner = await self.repo.get_by_id_or_raise(partner_id, "Partner")

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return partner

        # Validate name required for contact type
        new_type = update_data.get("partner_type", partner.partner_type)
        new_name = update_data.get("name", partner.name)
        if new_type == "contact" and not new_name:
            raise ValidationError("Contact-type partners must have a name")

        # VAT duplicate check
        new_vat = update_data.get("vat")
        if new_vat and new_vat != partner.vat:
            existing = await self.repo.find_by_vat(new_vat, exclude_id=partner_id)
            if existing:
                raise ConflictError(
                    f"Another partner already has VAT '{new_vat}': {existing.name}"
                )

        # Ref duplicate check
        new_ref = update_data.get("ref")
        if new_ref and new_ref != partner.ref:
            existing = await self.repo.find_by_ref(new_ref)
            if existing and existing.id != partner_id:
                raise ConflictError(
                    f"Another partner already has reference '{new_ref}': {existing.name}"
                )

        # Parent change — check for cycles
        new_parent_id = update_data.get("parent_id")
        if new_parent_id is not None and new_parent_id != partner.parent_id:
            if new_parent_id == partner_id:
                raise BusinessRuleError("A partner cannot be its own parent")
            if await self._would_create_cycle(partner_id, new_parent_id):
                raise BusinessRuleError("This parent assignment would create a cycle")

        # Apply updates
        for key, value in update_data.items():
            setattr(partner, key, value)

        # Recompute derived fields
        parent = None
        if partner.parent_id:
            parent = await self.repo.get_by_id(partner.parent_id)

        partner.display_name = self._compute_display_name(partner, parent)
        partner.commercial_partner_id = self._resolve_commercial_partner_id(partner, parent)
        await self.db.flush()

        # If VAT or commercial fields changed on a company, sync to descendants
        if partner.is_company and any(f in update_data for f in COMMERCIAL_FIELDS):
            await self._sync_commercial_to_descendants(partner)

        # If name changed, update display_name of children
        if "name" in update_data and partner.is_company:
            await self._update_children_display_names(partner)

        await event_bus.publish("partner.updated", {
            "partner_id": str(partner.id),
            "changed_fields": list(update_data.keys()),
        })

        return partner

    # ── Delete (soft) ─────────────────────────────────────────────────

    async def archive_partner(self, partner_id: uuid.UUID) -> Partner:
        """Soft-delete a partner by setting is_active=False."""
        partner = await self.repo.get_by_id_or_raise(partner_id, "Partner")
        partner.is_active = False
        await self.db.flush()

        await event_bus.publish("partner.archived", {"partner_id": str(partner.id)})
        return partner

    async def restore_partner(self, partner_id: uuid.UUID) -> Partner:
        """Restore an archived partner."""
        partner = await self.repo.get_by_id_or_raise(partner_id, "Partner")
        partner.is_active = True
        await self.db.flush()

        await event_bus.publish("partner.restored", {"partner_id": str(partner.id)})
        return partner

    async def delete_partner(self, partner_id: uuid.UUID) -> None:
        """Hard delete a partner (use with caution — prefer archive)."""
        partner = await self.repo.get_by_id_or_raise(partner_id, "Partner")

        # Check for children
        children = await self.repo.get_children(partner_id)
        if children:
            raise BusinessRuleError(
                f"Cannot delete partner with {len(children)} child contact(s). "
                "Archive instead, or reassign/delete children first."
            )

        await self.repo.delete(partner_id)
        await event_bus.publish("partner.deleted", {"partner_id": str(partner_id)})

    # ── Address Resolution (Odoo-style) ───────────────────────────────

    async def get_address(
        self, partner_id: uuid.UUID, address_types: list[str] | None = None
    ) -> dict[str, uuid.UUID | None]:
        """Find the best address for each requested type.

        Walks the partner hierarchy to find invoice/delivery/contact addresses.
        Returns a dict like: {"invoice": uuid, "delivery": uuid, "contact": uuid}

        If no specialized address is found, falls back to the partner itself.
        """
        if address_types is None:
            address_types = ["invoice", "delivery", "contact"]

        partner = await self.repo.get_by_id_or_raise(partner_id, "Partner")
        result: dict[str, uuid.UUID | None] = {}

        children = await self.repo.get_children(partner_id)

        for addr_type in address_types:
            # Find a child with matching type
            match = next(
                (c for c in children if c.partner_type == addr_type and c.is_active),
                None,
            )
            if match:
                result[addr_type] = match.id
            elif partner.parent_id:
                # Check parent's children
                siblings = await self.repo.get_children(partner.parent_id)
                sibling_match = next(
                    (s for s in siblings if s.partner_type == addr_type and s.is_active),
                    None,
                )
                result[addr_type] = sibling_match.id if sibling_match else partner_id
            else:
                result[addr_type] = partner_id

        return result

    # ── Stats ─────────────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        """Return contact statistics for dashboards."""
        return await self.repo.count_by_type()

    # ── Private: Display Name ─────────────────────────────────────────

    def _compute_display_name(self, partner: Partner, parent: Partner | None) -> str:
        """Compute display name following Odoo's pattern.

        - Company: just the name
        - Person under company: "Company, Person"
        - Address without name: "Address Type" label
        """
        if partner.partner_type != "contact" and not partner.name:
            type_labels = {
                "invoice": "Invoice Address",
                "delivery": "Delivery Address",
                "other": "Other Address",
            }
            return type_labels.get(partner.partner_type, "Address")

        if parent and parent.is_company and partner.name and not partner.is_company:
            return f"{parent.name}, {partner.name}"

        return partner.name or ""

    # ── Private: Commercial Partner ───────────────────────────────────

    def _resolve_commercial_partner_id(
        self, partner: Partner, parent: Partner | None
    ) -> uuid.UUID:
        """Walk up the hierarchy to find the top-level commercial entity."""
        if not parent:
            return partner.id
        if parent.commercial_partner_id:
            return parent.commercial_partner_id
        return parent.id

    async def _sync_commercial_from_parent(
        self, partner: Partner, parent: Partner
    ) -> None:
        """Copy commercial fields from the parent company to a new child."""
        for field in COMMERCIAL_FIELDS:
            parent_value = getattr(parent, field, None)
            if parent_value is not None:
                setattr(partner, field, parent_value)
        await self.db.flush()

    async def _sync_commercial_to_descendants(self, company: Partner) -> None:
        """Push commercial field changes from a company to all its descendants."""
        descendants = await self.repo.get_commercial_descendants(company.id)
        for desc in descendants:
            for field in COMMERCIAL_FIELDS:
                setattr(desc, field, getattr(company, field))
        if descendants:
            await self.db.flush()

    async def _update_children_display_names(self, company: Partner) -> None:
        """Recompute display_name for all children when company name changes."""
        children = await self.repo.get_children(company.id)
        for child in children:
            child.display_name = self._compute_display_name(child, company)
        if children:
            await self.db.flush()

    # ── Private: Cycle Detection ──────────────────────────────────────

    async def _would_create_cycle(
        self, partner_id: uuid.UUID, new_parent_id: uuid.UUID
    ) -> bool:
        """Check if assigning new_parent_id would create a parent cycle."""
        current_id = new_parent_id
        visited: set[uuid.UUID] = set()

        while current_id is not None:
            if current_id == partner_id:
                return True
            if current_id in visited:
                return True
            visited.add(current_id)

            parent = await self.repo.get_by_id(current_id)
            current_id = parent.parent_id if parent else None

        return False
