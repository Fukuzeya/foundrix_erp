"""Bank account service — manages bank accounts for partners."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError
from src.modules.contacts.models.partner import PartnerBankAccount
from src.modules.contacts.repositories.bank_repo import BankAccountRepository
from src.modules.contacts.repositories.partner_repo import PartnerRepository
from src.modules.contacts.schemas.partner import BankAccountCreate, BankAccountUpdate

logger = logging.getLogger(__name__)


class BankAccountService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = BankAccountRepository(db)
        self.partner_repo = PartnerRepository(db)

    async def add_bank_account(
        self, partner_id: uuid.UUID, data: BankAccountCreate
    ) -> PartnerBankAccount:
        """Add a bank account to a partner."""
        await self.partner_repo.get_by_id_or_raise(partner_id, "Partner")

        # Check duplicate account number
        existing = await self.repo.find_by_account_number(partner_id, data.account_number)
        if existing:
            raise ConflictError(
                f"Account number '{data.account_number}' already exists for this partner"
            )

        # If this is primary, clear other primaries
        if data.is_primary:
            await self.repo.clear_primary(partner_id)

        return await self.repo.create(
            partner_id=partner_id,
            **data.model_dump(),
        )

    async def update_bank_account(
        self, account_id: uuid.UUID, data: BankAccountUpdate
    ) -> PartnerBankAccount:
        account = await self.repo.get_by_id_or_raise(account_id, "BankAccount")

        update_data = data.model_dump(exclude_unset=True)

        # If setting as primary, clear others
        if update_data.get("is_primary"):
            await self.repo.clear_primary(account.partner_id)

        for key, value in update_data.items():
            setattr(account, key, value)
        await self.db.flush()
        await self.db.refresh(account)
        return account

    async def delete_bank_account(self, account_id: uuid.UUID) -> None:
        await self.repo.delete(account_id)

    async def list_bank_accounts(self, partner_id: uuid.UUID) -> list[PartnerBankAccount]:
        return await self.repo.get_by_partner(partner_id)
