"""Structured logging setup using Python's standard logging with JSON output.

In production, logs are emitted as JSON lines for ingestion by log
aggregators (ELK, Datadog, CloudWatch). In development, logs use
a human-readable format.
"""

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any

from src.core.config import settings


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON lines for structured log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        # Include extra fields added via logger.info("msg", extra={...})
        for key in ("tenant_id", "user_id", "request_id", "method", "path", "status_code"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, default=str)


class DevFormatter(logging.Formatter):
    """Human-readable log format for development."""

    FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.FORMAT, datefmt="%H:%M:%S")


def setup_logging() -> None:
    """Configure the root logger based on the environment.

    - Production: JSON to stdout, WARNING level
    - Development: colored human-readable, DEBUG level
    """
    root = logging.getLogger()

    # Clear existing handlers to avoid duplicates on reload
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if settings.is_production:
        handler.setFormatter(JSONFormatter())
        root.setLevel(logging.WARNING)
    else:
        handler.setFormatter(DevFormatter())
        root.setLevel(logging.DEBUG)

    root.addHandler(handler)

    # Quiet noisy libraries
    for noisy in ("asyncio", "sqlalchemy.engine", "httpcore", "httpx", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
