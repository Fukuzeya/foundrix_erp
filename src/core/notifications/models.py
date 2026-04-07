"""Notification models stored in the public schema.

Notifications are tenant-scoped but stored centrally for efficient
querying and cross-tenant platform admin views.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class NotificationChannel(str, enum.Enum):
    """Delivery channels for notifications."""

    IN_APP = "in_app"
    EMAIL = "email"
    BOTH = "both"


class NotificationPriority(str, enum.Enum):
    """Priority levels for notifications."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Notification(UUIDMixin, TimestampMixin, Base):
    """A notification sent to a user within a tenant context."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "is_read"),
        Index("ix_notifications_tenant_created", "tenant_id", "created_at"),
        {"schema": "public"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel", schema="public"),
        server_default=text("'in_app'"),
    )
    priority: Mapped[NotificationPriority] = mapped_column(
        Enum(NotificationPriority, name="notification_priority", schema="public"),
        server_default=text("'normal'"),
    )
    is_read: Mapped[bool] = mapped_column(server_default=text("false"))
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Module and entity that triggered the notification
    source_module: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<Notification user={self.user_id} title={self.title!r} read={self.is_read}>"
