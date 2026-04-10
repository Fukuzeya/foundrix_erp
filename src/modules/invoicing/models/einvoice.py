"""E-Invoice configuration and transmission log models.

Supports UBL 2.1, Peppol BIS 3.0, Factur-X (CII), and XRechnung formats
for electronic invoice generation and exchange.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class EInvoiceConfig(UUIDMixin, TimestampMixin, Base):
    """Configuration for e-invoicing formats and delivery endpoints.

    Each config defines a format (UBL, Peppol, Factur-X, XRechnung) and
    optional delivery endpoint for a given country or trading partner.
    """

    __tablename__ = "einvoice_configs"

    name: Mapped[str] = mapped_column(
        String(100),
        doc="Human-readable configuration name.",
    )
    format_type: Mapped[str] = mapped_column(
        String(20),
        doc="E-invoice format: ubl, peppol, facturx, xrechnung.",
    )
    country_code: Mapped[str | None] = mapped_column(
        String(2), nullable=True,
        doc="ISO 3166-1 alpha-2 country code this config applies to.",
    )
    eas_code: Mapped[str | None] = mapped_column(
        String(10), nullable=True,
        doc="Electronic Address Scheme code (e.g. 0088 for GLN, 9925 for VAT).",
    )
    endpoint_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        doc="Peppol participant endpoint identifier.",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"),
        doc="Whether this is the default config for its format type.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
        doc="Whether this configuration is currently active.",
    )
    settings: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        doc="Additional format-specific settings as JSON.",
    )

    def __repr__(self) -> str:
        return f"<EInvoiceConfig name={self.name!r} format={self.format_type}>"


class EInvoiceLog(UUIDMixin, TimestampMixin, Base):
    """Audit log for every e-invoice generation and transmission attempt.

    Tracks the full lifecycle: generation → validation → sending → delivery.
    """

    __tablename__ = "einvoice_logs"
    __table_args__ = (
        Index("ix_einvoice_logs_move_id", "move_id"),
        Index("ix_einvoice_logs_status", "status"),
        Index("ix_einvoice_logs_direction", "direction"),
    )

    move_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("moves.id", ondelete="CASCADE"),
        nullable=False,
        doc="The journal entry / invoice this log belongs to.",
    )
    format_type: Mapped[str] = mapped_column(
        String(20),
        doc="E-invoice format used: ubl, peppol, facturx, xrechnung.",
    )
    direction: Mapped[str] = mapped_column(
        String(10),
        doc="Direction: outbound or inbound.",
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'pending'"),
        doc="Lifecycle status: pending, generated, validated, sent, delivered, error.",
    )
    xml_content: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="The generated XML content.",
    )
    file_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        doc="Suggested file name for the XML document.",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="Error details if generation or transmission failed.",
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        doc="Timestamp when the document was sent to the network.",
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        doc="Timestamp when delivery was confirmed by the receiver.",
    )
    external_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        doc="External reference ID from the delivery network.",
    )

    def __repr__(self) -> str:
        return f"<EInvoiceLog move={self.move_id} format={self.format_type} status={self.status}>"
