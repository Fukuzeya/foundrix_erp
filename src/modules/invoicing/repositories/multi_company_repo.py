"""Repositories for inter-company rules and transactions."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.invoicing.models.multi_company import (
    InterCompanyRule,
    InterCompanyTransaction,
)


class InterCompanyRuleRepository(BaseRepository[InterCompanyRule]):
    """Repository for InterCompanyRule CRUD and lookups."""

    model = InterCompanyRule

    async def get_by_companies(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> list[InterCompanyRule]:
        """Return all rules between a specific source and target company."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.source_company_id == source_id,
                self.model.target_company_id == target_id,
            )
        )
        return list(result.scalars().all())

    async def get_active_rules(
        self,
        company_id: uuid.UUID | None = None,
    ) -> list[InterCompanyRule]:
        """Return active rules, optionally filtered by company (source or target)."""
        query = select(self.model).where(self.model.is_active.is_(True))
        if company_id is not None:
            query = query.where(
                or_(
                    self.model.source_company_id == company_id,
                    self.model.target_company_id == company_id,
                )
            )
        result = await self.db.execute(query.order_by(self.model.created_at.desc()))
        return list(result.scalars().all())

    async def find_matching_rule(
        self,
        source_company_id: uuid.UUID,
        rule_type: str,
    ) -> InterCompanyRule | None:
        """Find a single active rule for a source company and rule type."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.source_company_id == source_company_id,
                self.model.rule_type == rule_type,
                self.model.is_active.is_(True),
            ).limit(1)
        )
        return result.scalar_one_or_none()


class InterCompanyTransactionRepository(BaseRepository[InterCompanyTransaction]):
    """Repository for InterCompanyTransaction CRUD and lookups."""

    model = InterCompanyTransaction

    async def get_by_source_move(
        self, source_move_id: uuid.UUID,
    ) -> InterCompanyTransaction | None:
        """Find a transaction by its source move."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.source_move_id == source_move_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_target_move(
        self, target_move_id: uuid.UUID,
    ) -> InterCompanyTransaction | None:
        """Find a transaction by its target move."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.target_move_id == target_move_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_pending(self) -> list[InterCompanyTransaction]:
        """Return all transactions in 'pending' state."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.state == "pending")
            .order_by(self.model.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_failed(self) -> list[InterCompanyTransaction]:
        """Return all transactions in 'failed' state."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.state == "failed")
            .order_by(self.model.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_by_companies(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> list[InterCompanyTransaction]:
        """Return all transactions between a specific source and target company."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.source_company_id == source_id,
                self.model.target_company_id == target_id,
            ).order_by(self.model.created_at.desc())
        )
        return list(result.scalars().all())
