"""Partner repository — data access layer for the Partner model.

Encapsulates all SQLAlchemy queries for partners, including filtered
searches, hierarchy traversal, and duplicate detection.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.contacts.models.partner import Partner


class PartnerRepository(BaseRepository[Partner]):
    model = Partner

    async def find_by_email(self, email: str) -> Partner | None:
        result = await self.db.execute(
            select(self.model).where(
                self.model.email == email,
                self.model.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def find_by_ref(self, ref: str) -> Partner | None:
        result = await self.db.execute(
            select(self.model).where(self.model.ref == ref)
        )
        return result.scalar_one_or_none()

    async def find_by_vat(self, vat: str, exclude_id: uuid.UUID | None = None) -> Partner | None:
        """Find a partner with the same VAT (for duplicate detection)."""
        query = select(self.model).where(
            self.model.vat == vat,
            self.model.is_active.is_(True),
        )
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    def build_filtered_query(
        self,
        *,
        search: str | None = None,
        is_company: bool | None = None,
        is_customer: bool | None = None,
        is_vendor: bool | None = None,
        is_active: bool | None = True,
        partner_type: str | None = None,
        parent_id: uuid.UUID | None = None,
        country_code: str | None = None,
        industry_id: uuid.UUID | None = None,
        tag_id: str | None = None,
    ) -> Select:
        """Build a query with all supported filters."""
        query = select(self.model)

        if search:
            term = f"%{search}%"
            query = query.where(
                or_(
                    self.model.name.ilike(term),
                    self.model.email.ilike(term),
                    self.model.ref.ilike(term),
                    self.model.phone.ilike(term),
                    self.model.mobile.ilike(term),
                    self.model.display_name.ilike(term),
                )
            )

        if is_company is not None:
            query = query.where(self.model.is_company.is_(is_company))
        if is_customer is not None:
            query = query.where(self.model.is_customer.is_(is_customer))
        if is_vendor is not None:
            query = query.where(self.model.is_vendor.is_(is_vendor))
        if is_active is not None:
            query = query.where(self.model.is_active.is_(is_active))
        if partner_type is not None:
            query = query.where(self.model.partner_type == partner_type)
        if parent_id is not None:
            query = query.where(self.model.parent_id == parent_id)
        if country_code is not None:
            query = query.where(self.model.country_code == country_code)
        if industry_id is not None:
            query = query.where(self.model.industry_id == industry_id)
        if tag_id is not None:
            query = query.where(self.model.tag_ids.any(tag_id))

        query = query.order_by(self.model.name.asc())
        return query

    async def get_children(self, parent_id: uuid.UUID) -> list[Partner]:
        """Get all direct children of a partner."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.parent_id == parent_id,
                self.model.is_active.is_(True),
            ).order_by(self.model.name)
        )
        return list(result.scalars().all())

    async def get_commercial_descendants(self, commercial_partner_id: uuid.UUID) -> list[Partner]:
        """Get all partners sharing the same commercial partner."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.commercial_partner_id == commercial_partner_id,
                self.model.id != commercial_partner_id,
            )
        )
        return list(result.scalars().all())

    async def count_by_type(self) -> dict[str, int]:
        """Count partners grouped by type (for dashboard stats)."""
        result = await self.db.execute(
            select(self.model.partner_type, func.count())
            .where(self.model.is_active.is_(True))
            .group_by(self.model.partner_type)
        )
        return {row[0]: row[1] for row in result.all()}
