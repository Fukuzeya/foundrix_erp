"""Notification service for creating, querying, and managing notifications.

Modules use this to notify users about events in a standardized way.

Usage::

    from src.core.notifications import notification_service

    await notification_service.notify(
        db=db,
        user_id=user.id,
        tenant_id=tenant.id,
        title="Invoice approved",
        body="Invoice INV-001 has been approved by your manager.",
        channel=NotificationChannel.BOTH,
        source_module="accounting",
    )
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationPriority,
)

logger = logging.getLogger(__name__)


class NotificationService:
    """Manages notification lifecycle: create, read, mark-as-read."""

    async def notify(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        title: str,
        body: str,
        channel: NotificationChannel = NotificationChannel.IN_APP,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        source_module: str | None = None,
        source_entity_type: str | None = None,
        source_entity_id: str | None = None,
        metadata: dict | None = None,
    ) -> Notification:
        """Create and dispatch a notification."""
        notification = Notification(
            user_id=user_id,
            tenant_id=tenant_id,
            title=title,
            body=body,
            channel=channel,
            priority=priority,
            source_module=source_module,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            metadata=metadata,
        )
        db.add(notification)
        await db.flush()

        # If email channel, enqueue email task
        if channel in (NotificationChannel.EMAIL, NotificationChannel.BOTH):
            try:
                from src.core.tasks import task_queue

                await task_queue.enqueue(
                    "send_notification_email",
                    notification_id=str(notification.id),
                    user_id=str(user_id),
                )
            except Exception:
                logger.warning("Failed to enqueue notification email", exc_info=True)

        return notification

    async def get_user_notifications(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID | None = None,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Notification]:
        """Get notifications for a user, optionally filtered by tenant and read status."""
        query = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
        )
        if tenant_id:
            query = query.where(Notification.tenant_id == tenant_id)
        if unread_only:
            query = query.where(Notification.is_read.is_(False))
        query = query.offset(offset).limit(limit)

        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_unread_count(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> int:
        """Get the count of unread notifications for a user."""
        query = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        if tenant_id:
            query = query.where(Notification.tenant_id == tenant_id)
        result = await db.execute(query)
        return result.scalar() or 0

    async def mark_as_read(
        self,
        db: AsyncSession,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Mark a single notification as read."""
        await db.execute(
            update(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
        await db.flush()

    async def mark_all_as_read(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> int:
        """Mark all unread notifications as read. Returns count updated."""
        query = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
        if tenant_id:
            query = query.where(Notification.tenant_id == tenant_id)
        result = await db.execute(query)
        await db.flush()
        return result.rowcount


# Singleton
notification_service = NotificationService()
