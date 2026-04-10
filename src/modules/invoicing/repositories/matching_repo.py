"""Repositories for the 3-way matching system.

Provides data access for purchase orders, receipts, and bill matches.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.repository.base import BaseRepository
from src.modules.invoicing.models.matching import (
    BillMatch,
    PurchaseOrderReference,
    ReceiptReference,
)


class PurchaseOrderRepository(BaseRepository[PurchaseOrderReference]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(PurchaseOrderReference, db)

    async def find_by_po_number(self, po_number: str) -> PurchaseOrderReference | None:
        """Find a purchase order by its unique PO number."""
        result = await self.db.execute(
            select(PurchaseOrderReference)
            .options(selectinload(PurchaseOrderReference.lines))
            .where(PurchaseOrderReference.po_number == po_number)
        )
        return result.scalar_one_or_none()

    async def list_by_partner(
        self,
        partner_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PurchaseOrderReference]:
        """List purchase orders for a specific vendor/partner."""
        result = await self.db.execute(
            select(PurchaseOrderReference)
            .options(selectinload(PurchaseOrderReference.lines))
            .where(PurchaseOrderReference.partner_id == partner_id)
            .order_by(PurchaseOrderReference.order_date.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_unmatched(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PurchaseOrderReference]:
        """List purchase orders that have not been fully billed/completed."""
        result = await self.db.execute(
            select(PurchaseOrderReference)
            .options(selectinload(PurchaseOrderReference.lines))
            .where(PurchaseOrderReference.state.notin_(["billed", "done"]))
            .order_by(PurchaseOrderReference.order_date.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())


class ReceiptRepository(BaseRepository[ReceiptReference]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(ReceiptReference, db)

    async def list_by_po(
        self,
        po_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ReceiptReference]:
        """List receipts linked to a specific purchase order."""
        result = await self.db.execute(
            select(ReceiptReference)
            .options(selectinload(ReceiptReference.lines))
            .where(ReceiptReference.po_id == po_id)
            .order_by(ReceiptReference.receipt_date.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_unmatched(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ReceiptReference]:
        """List receipts that are not yet linked to a bill match."""
        # Receipts in 'done' state that have no corresponding BillMatch record
        subquery = select(BillMatch.receipt_id).where(BillMatch.receipt_id.isnot(None))
        result = await self.db.execute(
            select(ReceiptReference)
            .options(selectinload(ReceiptReference.lines))
            .where(
                ReceiptReference.state == "done",
                ReceiptReference.id.notin_(subquery),
            )
            .order_by(ReceiptReference.receipt_date.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())


class BillMatchRepository(BaseRepository[BillMatch]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(BillMatch, db)

    async def get_by_bill(self, bill_id: uuid.UUID) -> BillMatch | None:
        """Get the match record for a specific bill."""
        result = await self.db.execute(
            select(BillMatch)
            .options(
                selectinload(BillMatch.purchase_order),
                selectinload(BillMatch.receipt),
            )
            .where(BillMatch.bill_id == bill_id)
        )
        return result.scalar_one_or_none()

    async def get_by_po(
        self,
        po_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[BillMatch]:
        """List all bill matches for a specific purchase order."""
        result = await self.db.execute(
            select(BillMatch)
            .options(
                selectinload(BillMatch.purchase_order),
                selectinload(BillMatch.receipt),
            )
            .where(BillMatch.po_id == po_id)
            .order_by(BillMatch.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_exceptions(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[BillMatch]:
        """List all matches with exception status requiring manual review."""
        result = await self.db.execute(
            select(BillMatch)
            .options(
                selectinload(BillMatch.purchase_order),
                selectinload(BillMatch.receipt),
            )
            .where(BillMatch.match_status == "exception")
            .order_by(BillMatch.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_pending(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[BillMatch]:
        """List all matches pending validation."""
        result = await self.db.execute(
            select(BillMatch)
            .options(
                selectinload(BillMatch.purchase_order),
                selectinload(BillMatch.receipt),
            )
            .where(BillMatch.match_status == "pending")
            .order_by(BillMatch.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_summary_counts(self) -> dict[str, int]:
        """Get counts of bill matches grouped by status."""
        result = await self.db.execute(
            select(
                BillMatch.match_status,
                func.count().label("cnt"),
            ).group_by(BillMatch.match_status)
        )
        counts = {row[0]: row[1] for row in result.all()}
        return {
            "total_bills": sum(counts.values()),
            "matched": counts.get("matched", 0),
            "exceptions": counts.get("exception", 0),
            "pending": counts.get("pending", 0),
            "overridden": counts.get("overridden", 0),
        }
