"""Asset repositories."""

import uuid
from sqlalchemy import select
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.asset import Asset, AssetGroup, AssetDepreciationLine


class AssetGroupRepository(BaseRepository[AssetGroup]):
    model = AssetGroup

    async def list_active(self) -> list[AssetGroup]:
        result = await self.db.execute(
            select(self.model).where(self.model.is_active.is_(True))
            .order_by(self.model.name)
        )
        return list(result.scalars().all())


class AssetRepository(BaseRepository[Asset]):
    model = Asset

    async def get_by_state(self, state: str) -> list[Asset]:
        result = await self.db.execute(
            select(self.model).where(self.model.state == state)
            .order_by(self.model.acquisition_date.desc())
        )
        return list(result.scalars().all())

    async def get_pending_depreciation(self) -> list[Asset]:
        result = await self.db.execute(
            select(self.model).where(
                self.model.state == "open",
                self.model.book_value > self.model.salvage_value,
            ).order_by(self.model.acquisition_date)
        )
        return list(result.scalars().all())


class AssetDepreciationLineRepository(BaseRepository[AssetDepreciationLine]):
    model = AssetDepreciationLine

    async def get_by_asset(self, asset_id: uuid.UUID) -> list[AssetDepreciationLine]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.asset_id == asset_id)
            .order_by(self.model.depreciation_date)
        )
        return list(result.scalars().all())

    async def get_unposted(self, asset_id: uuid.UUID) -> list[AssetDepreciationLine]:
        result = await self.db.execute(
            select(self.model).where(
                self.model.asset_id == asset_id,
                self.model.move_id.is_(None),
            ).order_by(self.model.depreciation_date)
        )
        return list(result.scalars().all())
