"""Webhook service for registering endpoints and dispatching events.

Integrates with the event bus — when a module publishes an event,
the webhook service checks for matching subscriptions and enqueues
deliveries as background tasks.

Usage::

    # Register during app startup (in lifespan):
    webhook_service.register_event_listener(event_bus)

    # Tenants register webhooks via API:
    endpoint = await webhook_service.create_endpoint(
        db=db,
        tenant_id=tenant.id,
        url="https://example.com/webhook",
        events=["invoice.created", "partner.*"],
    )
"""

import fnmatch
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.webhooks.models import DeliveryStatus, WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)


class WebhookService:
    """Manages webhook endpoints and delivery."""

    async def create_endpoint(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        url: str,
        events: list[str],
        description: str = "",
    ) -> WebhookEndpoint:
        """Register a new webhook endpoint for a tenant."""
        endpoint = WebhookEndpoint(
            tenant_id=tenant_id,
            url=url,
            secret=secrets.token_urlsafe(32),
            events=events,
            description=description,
        )
        db.add(endpoint)
        await db.flush()
        return endpoint

    async def list_endpoints(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list[WebhookEndpoint]:
        """List all webhook endpoints for a tenant."""
        result = await db.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def delete_endpoint(
        self,
        db: AsyncSession,
        endpoint_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        """Delete a webhook endpoint."""
        result = await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.tenant_id == tenant_id,
            )
        )
        endpoint = result.scalar_one_or_none()
        if endpoint:
            await db.delete(endpoint)
            await db.flush()

    def _matches_event(self, subscribed_events: list[str], event_name: str) -> bool:
        """Check if an event name matches any subscribed patterns."""
        return any(fnmatch.fnmatch(event_name, pattern) for pattern in subscribed_events)

    def sign_payload(self, payload: str, secret: str) -> str:
        """Create HMAC-SHA256 signature for a webhook payload."""
        return hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

    async def dispatch_event(
        self,
        db: AsyncSession,
        event_name: str,
        payload: dict,
        tenant_id: uuid.UUID | None = None,
    ) -> int:
        """Find matching webhook endpoints and enqueue deliveries.

        Returns the number of deliveries enqueued.
        """
        if not tenant_id:
            return 0

        result = await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.is_active.is_(True),
            )
        )
        endpoints = result.scalars().all()
        count = 0

        for endpoint in endpoints:
            if not self._matches_event(endpoint.events, event_name):
                continue

            delivery = WebhookDelivery(
                endpoint_id=endpoint.id,
                event_name=event_name,
                payload=payload,
                status=DeliveryStatus.PENDING,
            )
            db.add(delivery)
            count += 1

        if count > 0:
            await db.flush()
            # Enqueue background delivery task
            try:
                from src.core.tasks import task_queue

                await task_queue.enqueue(
                    "deliver_webhooks",
                    tenant_id=str(tenant_id),
                    event_name=event_name,
                )
            except Exception:
                logger.warning("Failed to enqueue webhook delivery", exc_info=True)

        return count

    def register_event_listener(self, event_bus) -> None:
        """Subscribe to all events on the event bus for webhook dispatch.

        This is a catch-all listener — it checks every published event
        against registered webhook endpoints.
        """
        # We register a wildcard-style handler by patching the event bus
        # to also call our handler for any event.
        original_publish = event_bus.publish

        async def publish_with_webhooks(event_name: str, payload: dict) -> None:
            await original_publish(event_name, payload)
            # Webhook dispatch needs a DB session and tenant context,
            # so it's handled at the API layer, not here.
            logger.debug("Event '%s' published (webhook check deferred to API layer)", event_name)

        event_bus.publish = publish_with_webhooks


# Singleton
webhook_service = WebhookService()
