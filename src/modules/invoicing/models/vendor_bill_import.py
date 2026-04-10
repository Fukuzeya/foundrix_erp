"""Vendor bill import and email alias models."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class VendorBillImport(UUIDMixin, TimestampMixin, Base):
    """Tracks vendor bill imports from uploads, emails, or API integrations.

    Each record represents a single import attempt. The status progresses
    through: pending -> processing -> parsed -> created (or failed at any step).
    """

    __tablename__ = "vendor_bill_imports"
    __table_args__ = (
        Index("ix_vendor_bill_imports_status", "status"),
    )

    # ── Source information ────────────────────────────────────────────
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="manual_upload/email/api",
    )
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email_from: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Processing state ─────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'pending'"),
        doc="pending/processing/parsed/created/failed",
    )
    parsed_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Resolved references ──────────────────────────────────────────
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    move_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )

    # ── Extracted fields ─────────────────────────────────────────────
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Error tracking ───────────────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<VendorBillImport id={self.id} source={self.source_type} "
            f"status={self.status}>"
        )


class VendorBillEmailAlias(UUIDMixin, TimestampMixin, Base):
    """Email alias configuration for automatic vendor bill ingestion.

    When an email arrives at an alias address, the system creates a
    VendorBillImport record and optionally auto-creates the vendor bill
    in the target journal.
    """

    __tablename__ = "vendor_bill_email_aliases"

    alias_email: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True,
    )
    target_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    auto_create: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
    )

    def __repr__(self) -> str:
        return f"<VendorBillEmailAlias alias={self.alias_email!r} active={self.is_active}>"
