"""Account service — Chart of Accounts management.

Handles:
- Account CRUD with type validation and internal group derivation
- Code uniqueness enforcement
- Reconcile flag enforcement for receivable/payable types
- include_initial_balance derivation from account type
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError, NotFoundError, ValidationError
from src.modules.accounting.models.account import (
    Account,
    AccountTag,
    ACCOUNT_TYPE_GROUPS,
    MUST_RECONCILE_TYPES,
)
from src.modules.accounting.repositories.account_repo import (
    AccountRepository,
    AccountTagRepository,
)
from src.modules.accounting.schemas.account import (
    AccountCreate,
    AccountRead,
    AccountTagCreate,
    AccountUpdate,
)

logger = logging.getLogger(__name__)

# Account types that carry initial balance on balance sheet
INITIAL_BALANCE_TYPES = {
    "asset_receivable", "asset_cash", "asset_current", "asset_non_current",
    "asset_prepayments", "asset_fixed",
    "liability_payable", "liability_credit_card", "liability_current",
    "liability_non_current", "equity",
}


class AccountService:
    """Manages Chart of Accounts with business rule enforcement."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AccountRepository(db)
        self.tag_repo = AccountTagRepository(db)

    def build_filtered_query(
        self,
        *,
        search: str | None = None,
        account_type: str | None = None,
        internal_group: str | None = None,
        reconcile: bool | None = None,
        is_active: bool | None = True,
    ) -> Select:
        """Build a filtered query for account listing (delegates to repo)."""
        return self.repo.build_filtered_query(
            search=search, account_type=account_type,
            internal_group=internal_group, reconcile=reconcile, is_active=is_active,
        )

    async def create_account(self, data: AccountCreate) -> Account:
        """Create an account with derived internal_group and reconcile enforcement."""
        # Check code uniqueness
        existing = await self.repo.find_by_code(data.code)
        if existing:
            raise ConflictError(f"Account code '{data.code}' already exists")

        # Validate account type and derive internal group
        if data.account_type not in ACCOUNT_TYPE_GROUPS:
            raise ValidationError(f"Invalid account type: {data.account_type}")

        internal_group = ACCOUNT_TYPE_GROUPS[data.account_type]

        # Enforce reconcile for receivable/payable
        reconcile = data.reconcile
        if data.account_type in MUST_RECONCILE_TYPES:
            reconcile = True

        include_initial_balance = data.account_type in INITIAL_BALANCE_TYPES

        account = await self.repo.create(
            **data.model_dump(),
            internal_group=internal_group,
            reconcile=reconcile,
            include_initial_balance=include_initial_balance,
        )
        await self.db.flush()
        return account

    async def get_account(self, account_id: uuid.UUID) -> Account:
        """Get an account by ID or raise NotFoundError."""
        return await self.repo.get_by_id_or_raise(account_id, "Account")

    async def update_account(self, account_id: uuid.UUID, data: AccountUpdate) -> Account:
        """Update an account with re-derived fields if type changes."""
        account = await self.repo.get_by_id_or_raise(account_id, "Account")
        update_data = data.model_dump(exclude_unset=True)

        # If account_type is changing, re-derive internal_group and flags
        if "account_type" in update_data:
            new_type = update_data["account_type"]
            if new_type not in ACCOUNT_TYPE_GROUPS:
                raise ValidationError(f"Invalid account type: {new_type}")
            update_data["internal_group"] = ACCOUNT_TYPE_GROUPS[new_type]
            if new_type in MUST_RECONCILE_TYPES:
                update_data["reconcile"] = True
            update_data["include_initial_balance"] = new_type in INITIAL_BALANCE_TYPES

        # If code is changing, check uniqueness
        if "code" in update_data and update_data["code"] != account.code:
            existing = await self.repo.find_by_code(update_data["code"])
            if existing:
                raise ConflictError(f"Account code '{update_data['code']}' already exists")

        for key, value in update_data.items():
            setattr(account, key, value)

        await self.db.flush()
        await self.db.refresh(account)
        return account

    # ── Account Tags ─────────────────────────────────────────────────

    async def create_tag(self, data: AccountTagCreate) -> AccountTag:
        """Create an account tag with uniqueness check."""
        existing = await self.tag_repo.find_by_name(data.name, data.applicability)
        if existing:
            raise ConflictError(f"Account tag '{data.name}' already exists")
        tag = await self.tag_repo.create(**data.model_dump())
        await self.db.flush()
        return tag

    async def list_tags(self, applicability: str | None = None) -> list[AccountTag]:
        """List account tags, optionally filtered by applicability."""
        return await self.tag_repo.list_all()
