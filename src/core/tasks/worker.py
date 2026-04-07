"""Background task worker process.

Run with: python -m src.core.tasks.worker

Polls Redis for queued tasks and executes them. Each task runs
in its own try/except so a failing task doesn't crash the worker.
"""

import asyncio
import json
import logging

import redis.asyncio as redis

from src.core.config import settings
from src.core.tasks.queue import _task_registry

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    """Main worker loop: pop tasks from Redis and execute them."""
    from src.core.logging import setup_logging

    setup_logging()

    pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
    logger.info("Task worker started, waiting for jobs...")

    # Import all modules to register their tasks
    try:
        from src.core.registry.registry import registry

        registry.scan_modules("src.modules")
    except Exception:
        logger.warning("Module scanning failed in worker", exc_info=True)

    while True:
        try:
            # Blocking pop with 5-second timeout
            result = await pool.brpop("foundrix:tasks", timeout=5)
            if result is None:
                continue

            _, raw = result
            payload = json.loads(raw)
            task_name = payload["task"]
            kwargs = payload.get("kwargs", {})
            task_id = payload.get("id", "unknown")

            fn = _task_registry.get(task_name)
            if not fn:
                logger.error("Unknown task: %s (id=%s)", task_name, task_id)
                continue

            logger.info("Executing task %s (id=%s)", task_name, task_id)
            try:
                await fn(kwargs)
                logger.info("Task %s completed (id=%s)", task_name, task_id)
            except Exception:
                logger.exception("Task %s failed (id=%s)", task_name, task_id)

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Worker loop error")
            await asyncio.sleep(1)

    await pool.aclose()
    logger.info("Task worker shutting down")


if __name__ == "__main__":
    asyncio.run(run_worker())
