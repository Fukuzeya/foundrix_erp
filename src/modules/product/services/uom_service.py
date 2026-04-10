"""UoM service — unit of measure management and conversion."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, ConflictError, NotFoundError
from src.modules.product.models.uom import Uom, UomCategory
from src.modules.product.repositories.uom_repo import UomCategoryRepository, UomRepository
from src.modules.product.schemas.uom import (
    UomCategoryCreate,
    UomConvertRequest,
    UomConvertResponse,
    UomCreate,
    UomUpdate,
)

logger = logging.getLogger(__name__)


class UomService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.category_repo = UomCategoryRepository(db)
        self.uom_repo = UomRepository(db)

    async def list_categories(self) -> list[UomCategory]:
        """List all UoM categories."""
        return await self.category_repo.list_all()

    async def list_uoms(self, category_id: uuid.UUID | None = None) -> list[Uom]:
        """List UoMs, optionally filtered by category."""
        if category_id:
            return await self.uom_repo.get_by_category(category_id)
        return await self.uom_repo.list_all()

    async def get_uom(self, uom_id: uuid.UUID) -> Uom:
        """Get a UoM by ID."""
        return await self.uom_repo.get_by_id_or_raise(uom_id, "UoM")

    async def create_category(self, data: UomCategoryCreate) -> UomCategory:
        existing = await self.category_repo.find_by_name(data.name)
        if existing:
            raise ConflictError(f"UoM category '{data.name}' already exists")
        return await self.category_repo.create(**data.model_dump())

    async def create_uom(self, data: UomCreate) -> Uom:
        # Validate category
        category = await self.category_repo.get_by_id(data.category_id)
        if not category:
            raise NotFoundError("UomCategory", str(data.category_id))

        # If reference type, check no other reference exists
        if data.uom_type == "reference":
            existing_ref = await self.uom_repo.get_reference_uom(data.category_id)
            if existing_ref:
                raise BusinessRuleError(
                    f"Category '{category.name}' already has a reference UoM: '{existing_ref.name}'"
                )

        return await self.uom_repo.create(**data.model_dump())

    async def update_uom(self, uom_id: uuid.UUID, data: UomUpdate) -> Uom:
        uom = await self.uom_repo.get_by_id_or_raise(uom_id, "UoM")
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(uom, key, value)
        await self.db.flush()
        await self.db.refresh(uom)
        return uom

    async def convert(self, data: UomConvertRequest) -> UomConvertResponse:
        """Convert a quantity between two UoMs."""
        from_uom = await self.uom_repo.get_by_id_or_raise(data.from_uom_id, "UoM")
        to_uom = await self.uom_repo.get_by_id_or_raise(data.to_uom_id, "UoM")

        try:
            result = from_uom.convert(data.quantity, to_uom)
        except ValueError as e:
            raise BusinessRuleError(str(e))

        return UomConvertResponse(
            quantity=data.quantity,
            from_uom=from_uom.name,
            to_uom=to_uom.name,
            result=result,
        )
