"""In-process event bus for cross-module communication."""

from src.core.events.bus import EventBus, event_bus

__all__ = ["EventBus", "event_bus"]
