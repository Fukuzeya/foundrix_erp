"""Journal service — journal management with validation.

Handles:
- Journal CRUD with code uniqueness
- Account validation for journal accounts
- Type-specific validation rules
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError, NotFoundError, ValidationError
from src.modules.accounting.models.journal import Journal
from src.modules.accounting.repositories.account_repo import AccountRepository
from src.modules.accounting.repositories.journal_repo import JournalRepository
from src.modules.accounting.schemas.journal import JournalCreate, JournalUpdate

logger = logging.getLogger(__name__)


class JournalService:
    """Manages accounting journals with business rule enforcement."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = JournalRepository(db)
        self.account_repo = AccountRepository(db)

    async def list_journals(self, journal_type: str | None = None) -> list[Journal]:
        """List journals, optionally filtered by type."""
        if journal_type:
            return await self.repo.get_by_type(journal_type)
        return await self.repo.list_active()

    async def create_journal(self, data: JournalCreate) -> Journal:
        """Create a journal with code uniqueness and account validation."""
        # Check code uniqueness
        existing = await self.repo.find_by_code(data.code)
        if existing:
            raise ConflictError(f"Journal code '{data.code}' already exists")

        # Validate referenced accounts exist
        if data.default_account_id:
            account = await self.account_repo.get_by_id(data.default_account_id)
            if not account:
                raise NotFoundError("Account", str(data.default_account_id))

        if data.suspense_account_id:
            account = await self.account_repo.get_by_id(data.suspense_account_id)
            if not account:
                raise NotFoundError("Account", str(data.suspense_account_id))

        if data.profit_account_id:
            account = await self.account_repo.get_by_id(data.profit_account_id)
            if not account:
                raise NotFoundError("Account", str(data.profit_account_id))

        if data.loss_account_id:
            account = await self.account_repo.get_by_id(data.loss_account_id)
            if not account:
                raise NotFoundError("Account", str(data.loss_account_id))

        journal = await self.repo.create(**data.model_dump())
        await self.db.flush()
        return journal

    async def get_journal(self, journal_id: uuid.UUID) -> Journal:
        """Get a journal by ID or raise NotFoundError."""
        return await self.repo.get_by_id_or_raise(journal_id, "Journal")

    async def update_journal(self, journal_id: uuid.UUID, data: JournalUpdate) -> Journal:
        """Update a journal with validation."""
        journal = await self.repo.get_by_id_or_raise(journal_id, "Journal")
        update_data = data.model_dump(exclude_unset=True)

        # If code is changing, check uniqueness
        if "code" in update_data and update_data["code"] != journal.code:
            existing = await self.repo.find_by_code(update_data["code"])
            if existing:
                raise ConflictError(f"Journal code '{update_data['code']}' already exists")

        # Validate account references
        for account_field in ("default_account_id", "suspense_account_id", "profit_account_id", "loss_account_id"):
            if account_field in update_data and update_data[account_field]:
                account = await self.account_repo.get_by_id(update_data[account_field])
                if not account:
                    raise NotFoundError("Account", str(update_data[account_field]))

        for key, value in update_data.items():
            setattr(journal, key, value)

        await self.db.flush()
        await self.db.refresh(journal)
        return journal
