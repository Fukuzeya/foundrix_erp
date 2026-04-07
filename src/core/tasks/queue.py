"""Async task queue backed by Redis.

Provides a simple interface for enqueuing background jobs. The actual
worker process runs separately via ``python -m src.core.tasks.worker``.

Tasks are registered using the ``@task`` decorator and enqueued with
``task_queue.enqueue()``.
"""

import logging
from typing import Any, Callable, Awaitable

from src.core.config import settings

logger = logging.getLogger(__name__)

# Registry of task functions
_task_registry: dict[str, Callable[..., Awaitable[Any]]] = {}


def task(name: str) -> Callable:
    """Decorator to register an async function as a background task.

    Args:
        name: Unique task identifier (e.g. 'send_welcome_email').
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        _task_registry[name] = fn
        logger.debug("Registered task: %s", name)
        return fn

    return decorator


class TaskQueue:
    """Simple async task queue using Redis lists.

    For production, this can be swapped for SAQ, Celery, or ARQ
    by implementing the same interface.
    """

    def __init__(self) -> None:
        self._redis = None

    async def connect(self) -> None:
        """Initialize Redis connection for the task queue."""
        try:
            import redis.asyncio as redis

            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("Task queue connected to Redis")
        except Exception:
            logger.warning("Task queue Redis unavailable — tasks will run inline", exc_info=True)
            self._redis = None

    async def disconnect(self) -> None:
        """Close the Redis connection."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    async def enqueue(self, task_name: str, **kwargs: Any) -> str | None:
        """Enqueue a task for background execution.

        If Redis is unavailable, falls back to running the task inline
        (synchronously in the current request). This ensures the system
        works without Redis in development.

        Args:
            task_name: The registered task name.
            **kwargs: Arguments to pass to the task function.

        Returns:
            A task ID string, or None if run inline.
        """
        import json
        import uuid

        task_id = str(uuid.uuid4())
        payload = json.dumps({"id": task_id, "task": task_name, "kwargs": kwargs}, default=str)

        if self._redis:
            try:
                await self._redis.lpush("foundrix:tasks", payload)
                logger.info("Enqueued task %s (id=%s)", task_name, task_id)
                return task_id
            except Exception:
                logger.warning("Failed to enqueue %s, running inline", task_name, exc_info=True)

        # Fallback: run inline
        fn = _task_registry.get(task_name)
        if fn:
            try:
                await fn(kwargs)
                logger.info("Ran task %s inline", task_name)
            except Exception:
                logger.exception("Inline task %s failed", task_name)
        else:
            logger.warning("Unknown task: %s", task_name)

        return None

    @property
    def is_available(self) -> bool:
        return self._redis is not None


# Singleton
task_queue = TaskQueue()
