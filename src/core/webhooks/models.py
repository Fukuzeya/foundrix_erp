"""Webhook models for outbound event delivery.

Tenants can register webhook endpoints to receive real-time notifications
when events occur in the platform (e.g., invoice.created, partner.updated).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class WebhookEndpoint(UUIDMixin, TimestampMixin, Base):
    """A registered webhook URL that receives event payloads."""

    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        Index("ix_webhook_endpoints_tenant", "tenant_id"),
        {"schema": "public"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="HMAC secret for signing payloads. Generated on creation.",
    )
    events: Mapped[list[str]] = mapped_column(
        ARRAY(String(200)),
        nullable=False,
        doc="List of event patterns to subscribe to, e.g. ['invoice.*', 'partner.created'].",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    description: Mapped[str] = mapped_column(String(500), server_default=text("''"))

    deliveries: Mapped[list["WebhookDelivery"]] = relationship(
        back_populates="endpoint",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<WebhookEndpoint tenant={self.tenant_id} url={self.url!r}>"


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class WebhookDelivery(UUIDMixin, Base):
    """Record of a webhook delivery attempt."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_endpoint", "endpoint_id"),
        Index("ix_webhook_deliveries_created", "created_at"),
        {"schema": "public"},
    )

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status", schema="public"),
        server_default=text("'pending'"),
    )
    response_status: Mapped[int | None] = mapped_column(nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    endpoint: Mapped["WebhookEndpoint"] = relationship(back_populates="deliveries")

    def __repr__(self) -> str:
        return f"<WebhookDelivery event={self.event_name!r} status={self.status.value}>"
