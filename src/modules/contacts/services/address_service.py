"""Address service — manages additional addresses for partners."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import NotFoundError
from src.modules.contacts.models.partner import PartnerAddress
from src.modules.contacts.repositories.address_repo import AddressRepository
from src.modules.contacts.repositories.partner_repo import PartnerRepository
from src.modules.contacts.schemas.partner import AddressCreate, AddressUpdate

logger = logging.getLogger(__name__)


class AddressService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AddressRepository(db)
        self.partner_repo = PartnerRepository(db)

    async def add_address(
        self, partner_id: uuid.UUID, data: AddressCreate
    ) -> PartnerAddress:
        """Add a new address to a partner."""
        await self.partner_repo.get_by_id_or_raise(partner_id, "Partner")

        # If this is set as default, clear other defaults of same type
        if data.is_default:
            await self.repo.clear_default_for_type(partner_id, data.address_type)

        return await self.repo.create(
            partner_id=partner_id,
            **data.model_dump(),
        )

    async def update_address(
        self, address_id: uuid.UUID, data: AddressUpdate
    ) -> PartnerAddress:
        """Update an existing address."""
        address = await self.repo.get_by_id_or_raise(address_id, "Address")

        update_data = data.model_dump(exclude_unset=True)

        # If setting as default, clear others of same type
        if update_data.get("is_default"):
            addr_type = update_data.get("address_type", address.address_type)
            await self.repo.clear_default_for_type(address.partner_id, addr_type)

        for key, value in update_data.items():
            setattr(address, key, value)
        await self.db.flush()
        await self.db.refresh(address)
        return address

    async def delete_address(self, address_id: uuid.UUID) -> None:
        await self.repo.delete(address_id)

    async def list_addresses(self, partner_id: uuid.UUID) -> list[PartnerAddress]:
        return await self.repo.get_by_partner(partner_id)
