"""Analytic accounting service — plans, accounts, and budgets.

Handles:
- Analytic plan CRUD with hierarchy
- Analytic account CRUD with code uniqueness
- Budget CRUD with lines and validation
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from src.modules.accounting.models.analytic import (
    AnalyticPlan,
    AnalyticAccount,
    Budget,
    BudgetLine,
)
from src.modules.accounting.repositories.analytic_repo import (
    AnalyticPlanRepository,
    AnalyticAccountRepository,
    BudgetRepository,
)
from src.modules.accounting.schemas.analytic import (
    AnalyticPlanCreate,
    AnalyticPlanUpdate,
    AnalyticAccountCreate,
    AnalyticAccountUpdate,
    BudgetCreate,
    BudgetUpdate,
)

logger = logging.getLogger(__name__)


class AnalyticService:
    """Manages analytic plans, accounts, and budgets."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.plan_repo = AnalyticPlanRepository(db)
        self.account_repo = AnalyticAccountRepository(db)
        self.budget_repo = BudgetRepository(db)

    # ── Analytic Plans ───────────────────────────────────────────────

    async def list_plans(self) -> list[AnalyticPlan]:
        """List all active analytic plans."""
        return await self.plan_repo.list_active()

    async def create_plan(self, data: AnalyticPlanCreate) -> AnalyticPlan:
        """Create an analytic plan."""
        if data.parent_id:
            parent = await self.plan_repo.get_by_id(data.parent_id)
            if not parent:
                raise NotFoundError("AnalyticPlan", str(data.parent_id))

        plan = await self.plan_repo.create(**data.model_dump())
        await self.db.flush()
        return plan

    async def get_plan(self, plan_id: uuid.UUID) -> AnalyticPlan:
        """Get an analytic plan by ID."""
        return await self.plan_repo.get_by_id_or_raise(plan_id, "AnalyticPlan")

    async def update_plan(self, plan_id: uuid.UUID, data: AnalyticPlanUpdate) -> AnalyticPlan:
        """Update an analytic plan."""
        plan = await self.plan_repo.get_by_id_or_raise(plan_id, "AnalyticPlan")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(plan, key, value)

        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    # ── Analytic Accounts ────────────────────────────────────────────

    async def list_accounts(self, plan_id: uuid.UUID | None = None) -> list[AnalyticAccount]:
        """List analytic accounts, optionally filtered by plan."""
        if plan_id:
            return await self.account_repo.get_by_plan(plan_id)
        return await self.account_repo.list_all()

    async def create_account(self, data: AnalyticAccountCreate) -> AnalyticAccount:
        """Create an analytic account with plan and code validation."""
        # Validate plan exists
        plan = await self.plan_repo.get_by_id(data.plan_id)
        if not plan:
            raise NotFoundError("AnalyticPlan", str(data.plan_id))

        # Check code uniqueness if provided
        if data.code:
            existing = await self.account_repo.find_by_code(data.code)
            if existing:
                raise ConflictError(f"Analytic account code '{data.code}' already exists")

        account = await self.account_repo.create(**data.model_dump())
        await self.db.flush()
        return account

    async def get_account(self, account_id: uuid.UUID) -> AnalyticAccount:
        """Get an analytic account by ID."""
        return await self.account_repo.get_by_id_or_raise(account_id, "AnalyticAccount")

    async def update_account(self, account_id: uuid.UUID, data: AnalyticAccountUpdate) -> AnalyticAccount:
        """Update an analytic account."""
        account = await self.account_repo.get_by_id_or_raise(account_id, "AnalyticAccount")
        update_data = data.model_dump(exclude_unset=True)

        # Code uniqueness check
        if "code" in update_data and update_data["code"] and update_data["code"] != account.code:
            existing = await self.account_repo.find_by_code(update_data["code"])
            if existing:
                raise ConflictError(f"Analytic account code '{update_data['code']}' already exists")

        for key, value in update_data.items():
            setattr(account, key, value)

        await self.db.flush()
        await self.db.refresh(account)
        return account

    # ── Budgets ──────────────────────────────────────────────────────

    async def list_budgets(self) -> list[Budget]:
        """List all budgets."""
        return await self.budget_repo.list_all()

    async def create_budget(self, data: BudgetCreate) -> Budget:
        """Create a budget with its lines."""
        if data.date_from >= data.date_to:
            raise ValidationError("Budget start date must be before end date")

        budget_data = data.model_dump(exclude={"lines"})
        budget = await self.budget_repo.create(**budget_data)

        if data.lines:
            for line_data in data.lines:
                if line_data.date_from < data.date_from or line_data.date_to > data.date_to:
                    raise ValidationError("Budget line dates must be within budget period")
                line = BudgetLine(budget_id=budget.id, **line_data.model_dump())
                self.db.add(line)

        await self.db.flush()
        await self.db.refresh(budget)
        return budget

    async def get_budget(self, budget_id: uuid.UUID) -> Budget:
        """Get a budget by ID."""
        return await self.budget_repo.get_by_id_or_raise(budget_id, "Budget")

    async def update_budget(self, budget_id: uuid.UUID, data: BudgetUpdate) -> Budget:
        """Update a budget."""
        budget = await self.budget_repo.get_by_id_or_raise(budget_id, "Budget")
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(budget, key, value)

        await self.db.flush()
        await self.db.refresh(budget)
        return budget
