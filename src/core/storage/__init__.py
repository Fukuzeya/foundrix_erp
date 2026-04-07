"""File storage abstraction with pluggable backends."""

from src.core.storage.base import StorageBackend
from src.core.storage.local import LocalStorageBackend

__all__ = ["StorageBackend", "LocalStorageBackend"]
