"""Asset management service — depreciation, amortization, and deferred revenue/expense.

Handles:
- Asset creation and validation
- Depreciation schedule generation (linear, degressive, manual)
- Automatic depreciation journal entry posting
- Asset disposal and sale
- Deferred revenue/expense recognition
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from dateutil.relativedelta import relativedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.accounting.models.asset import Asset, AssetDepreciationLine, AssetGroup
from src.modules.accounting.repositories.asset_repo import (
    AssetRepository,
    AssetGroupRepository,
    AssetDepreciationLineRepository,
)
from src.modules.accounting.schemas.asset import AssetCreate

logger = logging.getLogger(__name__)


class AssetService:
    """Manages fixed assets and depreciation schedules."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.asset_repo = AssetRepository(db)
        self.group_repo = AssetGroupRepository(db)
        self.dep_line_repo = AssetDepreciationLineRepository(db)

    async def list_assets(self, state: str | None = None) -> list[Asset]:
        """List assets, optionally filtered by state."""
        if state:
            return await self.asset_repo.get_by_state(state)
        return await self.asset_repo.list_all()

    async def get_asset(self, asset_id: uuid.UUID) -> Asset:
        """Get an asset by ID."""
        return await self.asset_repo.get_by_id_or_raise(asset_id, "Asset")

    async def create_asset(self, data: AssetCreate) -> Asset:
        """Create an asset and generate its depreciation schedule."""
        if data.asset_group_id:
            group = await self.group_repo.get_by_id(data.asset_group_id)
            if not group:
                raise NotFoundError("AssetGroup", str(data.asset_group_id))

        asset = Asset(**data.model_dump())
        self.db.add(asset)
        await self.db.flush()
        await self.db.refresh(asset)

        await event_bus.publish("asset.created", {"asset_id": str(asset.id)})
        return asset

    async def confirm_asset(self, asset_id: uuid.UUID) -> Asset:
        """Confirm asset and generate depreciation schedule."""
        asset = await self.asset_repo.get_by_id_or_raise(asset_id, "Asset")

        if asset.state != "draft":
            raise BusinessRuleError(f"Cannot confirm asset in state '{asset.state}'")

        # Generate depreciation schedule
        await self._generate_depreciation_board(asset)

        asset.state = "open"
        await self.db.flush()

        await event_bus.publish("asset.confirmed", {"asset_id": str(asset.id)})
        return asset

    async def post_depreciation(self, asset_id: uuid.UUID) -> list[AssetDepreciationLine]:
        """Post all unposted depreciation lines up to today."""
        asset = await self.asset_repo.get_by_id_or_raise(asset_id, "Asset")

        if asset.state != "open":
            raise BusinessRuleError("Can only depreciate open assets")

        unposted = await self.dep_line_repo.get_unposted(asset_id)
        today = date.today()
        posted_lines = []

        for line in unposted:
            if line.depreciation_date <= today:
                # Create journal entry for this depreciation
                from src.modules.accounting.services.move_service import MoveService
                move_svc = MoveService(self.db)

                from src.modules.accounting.schemas.move import MoveCreate, MoveLineCreate
                move_data = MoveCreate(
                    move_type="entry",
                    journal_id=asset.journal_id,
                    date=line.depreciation_date,
                    ref=f"Depreciation: {asset.name}",
                    lines=[
                        MoveLineCreate(
                            account_id=asset.depreciation_account_id,
                            debit=line.amount,
                            credit=0.0,
                            name=f"Depreciation: {asset.name}",
                        ),
                        MoveLineCreate(
                            account_id=asset.account_id,
                            debit=0.0,
                            credit=line.amount,
                            name=f"Depreciation: {asset.name}",
                        ),
                    ],
                )
                move = await move_svc.create_move(move_data)
                await move_svc.post_move(move.id)

                line.move_id = move.id
                asset.book_value = round(asset.book_value - line.amount, 2)
                posted_lines.append(line)

        await self.db.flush()
        return posted_lines

    async def close_asset(self, asset_id: uuid.UUID) -> Asset:
        """Close a fully depreciated asset."""
        asset = await self.asset_repo.get_by_id_or_raise(asset_id, "Asset")

        if asset.state != "open":
            raise BusinessRuleError("Can only close open assets")

        asset.state = "close"
        await self.db.flush()

        await event_bus.publish("asset.closed", {"asset_id": str(asset.id)})
        return asset

    async def dispose_asset(
        self, asset_id: uuid.UUID, *, disposal_date: date | None = None,
        sale_amount: float = 0.0,
    ) -> Asset:
        """Dispose of an asset (sell or scrap) and record gain/loss."""
        asset = await self.asset_repo.get_by_id_or_raise(asset_id, "Asset")

        if asset.state not in ("open", "close"):
            raise BusinessRuleError("Can only dispose open or closed assets")

        # Post any remaining depreciation up to disposal date
        # Record disposal entry
        disposal_date = disposal_date or date.today()
        gain_loss = sale_amount - asset.book_value

        asset.state = "disposed"
        asset.disposal_date = disposal_date
        await self.db.flush()

        await event_bus.publish("asset.disposed", {
            "asset_id": str(asset.id),
            "gain_loss": gain_loss,
        })
        return asset

    async def _generate_depreciation_board(self, asset: Asset) -> None:
        """Generate the depreciation schedule based on method and duration."""
        depreciable = asset.original_value - asset.salvage_value
        if depreciable <= 0:
            return

        total_months = asset.method_period * asset.method_number
        if total_months <= 0:
            return

        start_date = asset.first_depreciation_date or asset.acquisition_date
        current_date = start_date

        if asset.method == "linear":
            period_amount = round(depreciable / asset.method_number, 2)
            remaining = depreciable

            for i in range(asset.method_number):
                # Last period gets the remainder to avoid rounding errors
                amount = period_amount if i < asset.method_number - 1 else remaining
                remaining -= amount

                accumulated = depreciable - remaining

                line = AssetDepreciationLine(
                    asset_id=asset.id,
                    sequence=i + 1,
                    depreciation_date=current_date,
                    amount=round(amount, 2),
                    depreciated_value=round(accumulated, 2),
                    remaining_value=round(remaining, 2),
                )
                self.db.add(line)

                current_date = current_date + relativedelta(months=asset.method_period)

        elif asset.method == "degressive":
            remaining = depreciable
            degressive_rate = asset.method_progress_factor or 2.0
            linear_rate = 1.0 / asset.method_number

            for i in range(asset.method_number):
                degressive_amount = remaining * degressive_rate * linear_rate
                linear_amount = depreciable * linear_rate
                amount = max(degressive_amount, linear_amount)
                amount = min(amount, remaining)

                remaining -= amount

                line = AssetDepreciationLine(
                    asset_id=asset.id,
                    sequence=i + 1,
                    depreciation_date=current_date,
                    amount=round(amount, 2),
                    depreciated_value=round(depreciable - remaining, 2),
                    remaining_value=round(remaining, 2),
                )
                self.db.add(line)

                current_date = current_date + relativedelta(months=asset.method_period)

                if remaining <= 0.01:
                    break

        await self.db.flush()
