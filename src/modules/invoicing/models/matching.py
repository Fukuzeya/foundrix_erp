"""3-Way Matching models — Purchase Order / Receipt / Vendor Bill matching.

The 3-way matching system ensures that vendor bills are only approved for
payment when they agree with the original purchase order AND the goods
receipt. This prevents overpayment, duplicate payments, and fraud.

Match types:
- two_way: PO ↔ Bill (quantity and price match)
- three_way: PO ↔ Receipt ↔ Bill (adds received-qty verification)

Match statuses:
- pending: Match created, awaiting validation
- matched: All documents agree within tolerance
- exception: Variance exceeds tolerance, needs manual review
- overridden: Exception was manually approved with a reason
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class MatchingRule(UUIDMixin, TimestampMixin, Base):
    """Configuration for how purchase-to-bill matching is evaluated.

    Organizations can define tolerance thresholds (fixed amount or percentage)
    and choose between 2-way and 3-way matching. When ``auto_validate`` is
    True, matches within tolerance are approved automatically.
    """

    __tablename__ = "matching_rules"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    match_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'three_way'"),
        doc="two_way or three_way.",
    )
    tolerance_amount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Maximum allowed absolute dollar variance.",
    )
    tolerance_percent: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Maximum allowed percentage variance.",
    )
    auto_validate: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"),
        doc="Automatically validate matches within tolerance.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
    )

    def __repr__(self) -> str:
        return f"<MatchingRule name={self.name!r} type={self.match_type}>"


class PurchaseOrderReference(UUIDMixin, TimestampMixin, Base):
    """A purchase order header used as the reference document for matching.

    States:
    - confirmed: PO issued to vendor
    - received: Goods partially or fully received
    - billed: Vendor bill matched
    - done: Fully received and billed
    """

    __tablename__ = "purchase_order_references"
    __table_args__ = (
        Index("ix_purchase_order_references_po_number", "po_number"),
        Index("ix_purchase_order_references_partner_id", "partner_id"),
        Index("ix_purchase_order_references_state", "state"),
    )

    po_number: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        doc="Unique purchase order number (e.g. PO/2026/0042).",
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
        doc="Vendor / supplier partner ID.",
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(3), server_default=text("'USD'"),
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'confirmed'"),
        doc="confirmed/received/billed/done.",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<PurchaseOrderReference po={self.po_number!r} state={self.state}>"


class PurchaseOrderLine(UUIDMixin, TimestampMixin, Base):
    """A single line on a purchase order — one item being procured."""

    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        Index("ix_purchase_order_lines_order_id", "order_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_references.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity_ordered: Mapped[float] = mapped_column(Float, nullable=False)
    quantity_received: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )
    quantity_billed: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )
    price_unit: Mapped[float] = mapped_column(Float, nullable=False)
    discount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Discount percentage (0-100).",
    )
    tax_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True,
    )
    sequence: Mapped[int] = mapped_column(
        Integer, server_default=text("10"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    order: Mapped["PurchaseOrderReference"] = relationship(
        back_populates="lines",
    )

    @property
    def line_total(self) -> float:
        """Computed line total: qty * price * (1 - discount/100)."""
        return self.quantity_ordered * self.price_unit * (1.0 - self.discount / 100.0)

    def __repr__(self) -> str:
        return (
            f"<PurchaseOrderLine desc={self.description!r} "
            f"qty={self.quantity_ordered} price={self.price_unit}>"
        )


class ReceiptReference(UUIDMixin, TimestampMixin, Base):
    """A goods receipt header — proof that ordered goods were delivered.

    Links back to the originating purchase order when applicable.
    """

    __tablename__ = "receipt_references"
    __table_args__ = (
        Index("ix_receipt_references_po_id", "po_id"),
        Index("ix_receipt_references_partner_id", "partner_id"),
    )

    receipt_number: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        doc="Unique receipt / delivery note number.",
    )
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_order_references.id", ondelete="SET NULL"),
        nullable=True,
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'done'"),
        doc="done/cancelled.",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    lines: Mapped[list["ReceiptLine"]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    purchase_order: Mapped["PurchaseOrderReference | None"] = relationship(
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ReceiptReference number={self.receipt_number!r} state={self.state}>"


class ReceiptLine(UUIDMixin, TimestampMixin, Base):
    """A single line on a receipt — one item received."""

    __tablename__ = "receipt_lines"
    __table_args__ = (
        Index("ix_receipt_lines_receipt_id", "receipt_id"),
        Index("ix_receipt_lines_po_line_id", "po_line_id"),
    )

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipt_references.id", ondelete="CASCADE"),
        nullable=False,
    )
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity_received: Mapped[float] = mapped_column(Float, nullable=False)
    sequence: Mapped[int] = mapped_column(
        Integer, server_default=text("10"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    receipt: Mapped["ReceiptReference"] = relationship(
        back_populates="lines",
    )
    po_line: Mapped["PurchaseOrderLine | None"] = relationship(
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<ReceiptLine desc={self.description!r} qty={self.quantity_received}>"
        )


class BillMatch(UUIDMixin, TimestampMixin, Base):
    """The result of matching a vendor bill against a PO and/or receipt.

    Tracks the amounts from each document and the computed variance.
    Exception matches require manual override with a documented reason.
    """

    __tablename__ = "bill_matches"
    __table_args__ = (
        Index("ix_bill_matches_bill_id", "bill_id"),
        Index("ix_bill_matches_po_id", "po_id"),
        Index("ix_bill_matches_match_status", "match_status"),
    )

    bill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
        doc="FK concept to moves table (vendor bill).",
    )
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_order_references.id", ondelete="SET NULL"),
        nullable=True,
    )
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("receipt_references.id", ondelete="SET NULL"),
        nullable=True,
    )

    match_type: Mapped[str] = mapped_column(
        String(20),
        doc="two_way or three_way.",
    )
    match_status: Mapped[str] = mapped_column(
        String(20), server_default=text("'pending'"),
        doc="pending/matched/exception/overridden.",
    )

    # ── Amounts from each document ────────────────────────────────────
    po_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    receipt_amount: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        doc="Calculated from received qty * unit price on PO lines.",
    )
    bill_amount: Mapped[float] = mapped_column(Float, nullable=False)

    # ── Variance ──────────────────────────────────────────────────────
    variance_amount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )
    variance_percent: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
    )

    # ── Approval / Override ───────────────────────────────────────────
    matched_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
        doc="User who approved / validated the match.",
    )
    matched_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
    exception_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="Reason for the exception or the override justification.",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    purchase_order: Mapped["PurchaseOrderReference | None"] = relationship(
        lazy="selectin",
    )
    receipt: Mapped["ReceiptReference | None"] = relationship(
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<BillMatch bill={self.bill_id} status={self.match_status} "
            f"variance={self.variance_amount}>"
        )
