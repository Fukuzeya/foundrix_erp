"""Simple async in-process event bus for cross-module communication.

Modules subscribe to named events and publish payloads without importing
each other directly. This enables loose coupling between modules — for
example, the accounting module can listen for ``partner.created`` events
published by the contacts module.

Usage::

    from src.core.events.bus import event_bus

    # In module startup (on_startup hook):
    event_bus.subscribe("partner.created", handle_new_partner)

    # In service code:
    await event_bus.publish("partner.created", {"partner_id": "..."})
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """Async in-process publish/subscribe event bus.

    Handlers are called concurrently via ``asyncio.gather`` when an event
    is published. A failing handler does not prevent other handlers from
    running — errors are logged and suppressed.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register a handler for a named event.

        Args:
            event_name: The event identifier (e.g. ``'partner.created'``).
            handler: An async callable that accepts a payload dict.
        """
        self._subscribers[event_name].append(handler)
        logger.debug("Subscribed %s to event '%s'", handler.__qualname__, event_name)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove a handler from a named event.

        Args:
            event_name: The event identifier.
            handler: The handler to remove.

        Raises:
            ValueError: If the handler is not subscribed to this event.
        """
        try:
            self._subscribers[event_name].remove(handler)
        except ValueError:
            raise ValueError(
                f"Handler {handler.__qualname__} is not subscribed to '{event_name}'"
            ) from None

    async def publish(self, event_name: str, payload: dict[str, Any]) -> None:
        """Publish an event to all subscribed handlers.

        All handlers run concurrently. Errors in individual handlers are
        logged but do not propagate — other handlers still execute.

        Args:
            event_name: The event identifier.
            payload: Data dict passed to each handler.
        """
        handlers = self._subscribers.get(event_name)
        if not handlers:
            return

        logger.debug(
            "Publishing event '%s' to %d handler(s)", event_name, len(handlers)
        )

        results = await asyncio.gather(
            *(self._safe_call(handler, event_name, payload) for handler in handlers),
        )

        failures = sum(1 for r in results if r is False)
        if failures:
            logger.warning(
                "Event '%s': %d/%d handlers failed", event_name, failures, len(handlers)
            )

    def clear(self) -> None:
        """Remove all subscriptions. Primarily used in testing."""
        self._subscribers.clear()

    async def _safe_call(
        self,
        handler: EventHandler,
        event_name: str,
        payload: dict[str, Any],
    ) -> bool:
        """Call a handler and catch any exceptions.

        Returns True on success, False on failure.
        """
        try:
            await handler(payload)
            return True
        except Exception:
            logger.exception(
                "Handler %s failed for event '%s'",
                handler.__qualname__,
                event_name,
            )
            return False


# Singleton event bus used throughout the application
event_bus = EventBus()
