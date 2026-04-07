"""Background task queue using SAQ (Simple Async Queue) backed by Redis.

SAQ is lighter than Celery for async Python applications. It uses Redis
as a broker and supports scheduling, retries, and concurrency control.

Usage::

    from src.core.tasks import task_queue, task

    @task("send_welcome_email")
    async def send_welcome_email(ctx, user_id: str, tenant_id: str):
        # ... send email ...
        pass

    # Enqueue from anywhere:
    await task_queue.enqueue("send_welcome_email", user_id="...", tenant_id="...")
"""

from src.core.tasks.queue import TaskQueue, task_queue, task

__all__ = ["TaskQueue", "task_queue", "task"]
