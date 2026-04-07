"""Tests for the event bus."""

import pytest
from src.core.events import EventBus


@pytest.mark.asyncio
async def test_publish_subscribe():
    bus = EventBus()
    received = []

    async def handler(payload):
        received.append(payload)

    bus.subscribe("test.event", handler)
    await bus.publish("test.event", {"key": "value"})

    assert len(received) == 1
    assert received[0] == {"key": "value"}


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    received = []

    async def handler(payload):
        received.append(payload)

    bus.subscribe("test.event", handler)
    bus.unsubscribe("test.event", handler)
    await bus.publish("test.event", {"key": "value"})

    assert len(received) == 0


@pytest.mark.asyncio
async def test_failing_handler_does_not_block_others():
    bus = EventBus()
    results = []

    async def bad_handler(payload):
        raise ValueError("boom")

    async def good_handler(payload):
        results.append("ok")

    bus.subscribe("test.event", bad_handler)
    bus.subscribe("test.event", good_handler)
    await bus.publish("test.event", {})

    assert results == ["ok"]
