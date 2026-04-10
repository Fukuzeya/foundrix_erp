"""Analytic accounting repositories."""

import uuid
from sqlalchemy import select, func
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.analytic import (
    AnalyticPlan,
    AnalyticAccount,
    AnalyticLine,
    Budget,
    BudgetLine,
)


class AnalyticPlanRepository(BaseRepository[AnalyticPlan]):
    model = AnalyticPlan

    async def list_active(self) -> list[AnalyticPlan]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())


class AnalyticAccountRepository(BaseRepository[AnalyticAccount]):
    model = AnalyticAccount

    async def get_by_plan(self, plan_id: uuid.UUID) -> list[AnalyticAccount]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.plan_id == plan_id, self.model.is_active.is_(True))
            .order_by(self.model.code, self.model.name)
        )
        return list(result.scalars().all())

    async def find_by_code(self, code: str) -> AnalyticAccount | None:
        result = await self.db.execute(
            select(self.model).where(self.model.code == code)
        )
        return result.scalar_one_or_none()


class AnalyticLineRepository(BaseRepository[AnalyticLine]):
    model = AnalyticLine

    async def get_by_account(self, account_id: uuid.UUID) -> list[AnalyticLine]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.account_id == account_id)
            .order_by(self.model.date.desc())
        )
        return list(result.scalars().all())

    async def get_account_balance(self, account_id: uuid.UUID) -> float:
        result = await self.db.execute(
            select(func.coalesce(func.sum(self.model.amount), 0))
            .where(self.model.account_id == account_id)
        )
        return result.scalar() or 0.0


class BudgetRepository(BaseRepository[Budget]):
    model = Budget


class BudgetLineRepository(BaseRepository[BudgetLine]):
    model = BudgetLine
