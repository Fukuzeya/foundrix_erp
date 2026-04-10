"""Incoterm service — CRUD for Incoterms 2020 reference data."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError, NotFoundError
from src.modules.invoicing.models.incoterm import Incoterm
from src.modules.invoicing.repositories.incoterm_repo import IncotermRepository
from src.modules.invoicing.schemas.incoterm import IncotermCreate, IncotermUpdate


class IncotermService:
    """Manages Incoterms reference data."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = IncotermRepository(db)

    async def get(self, incoterm_id: uuid.UUID) -> Incoterm:
        """Get an incoterm by ID."""
        incoterm = await self.repo.get_by_id(incoterm_id)
        if not incoterm:
            raise NotFoundError("Incoterm", str(incoterm_id))
        return incoterm

    async def get_by_code(self, code: str) -> Incoterm:
        """Get an incoterm by its 3-letter code."""
        incoterm = await self.repo.find_by_code(code)
        if not incoterm:
            raise NotFoundError("Incoterm", code)
        return incoterm

    async def list_active(self) -> list[Incoterm]:
        """List all active incoterms."""
        return await self.repo.list_active()

    async def create(self, data: IncotermCreate) -> Incoterm:
        """Create a new incoterm."""
        existing = await self.repo.find_by_code(data.code)
        if existing:
            raise ConflictError(f"Incoterm with code '{data.code}' already exists")

        incoterm = Incoterm(
            code=data.code.upper(),
            name=data.name,
            description=data.description,
            is_active=data.is_active,
        )
        self.db.add(incoterm)
        await self.db.flush()
        await self.db.refresh(incoterm)
        return incoterm

    async def update(self, incoterm_id: uuid.UUID, data: IncotermUpdate) -> Incoterm:
        """Update an existing incoterm."""
        incoterm = await self.repo.get_by_id(incoterm_id)
        if not incoterm:
            raise NotFoundError("Incoterm", str(incoterm_id))

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(incoterm, key, value)

        await self.db.flush()
        await self.db.refresh(incoterm)
        return incoterm
