"""Abstract storage backend for file operations.

Provides a pluggable interface so the application can switch between
local filesystem, S3, Azure Blob, GCS, etc. without changing module code.

Usage in modules::

    from src.core.storage import get_storage

    storage = get_storage()
    path = await storage.save("invoices", filename, file_content, tenant_id="acme")
    url = await storage.get_url(path)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class StoredFile:
    """Metadata about a stored file."""

    path: str
    filename: str
    content_type: str
    size: int
    tenant_id: str | None = None


class StorageBackend(ABC):
    """Abstract interface for file storage backends."""

    @abstractmethod
    async def save(
        self,
        folder: str,
        filename: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        tenant_id: str | None = None,
    ) -> StoredFile:
        """Save a file and return its metadata."""
        ...

    @abstractmethod
    async def read(self, path: str) -> bytes:
        """Read file contents by path."""
        ...

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete a file by path."""
        ...

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if a file exists at the given path."""
        ...

    @abstractmethod
    async def get_url(self, path: str, *, expires_in: int = 3600) -> str:
        """Get a URL for accessing the file.

        For local storage, returns a relative path.
        For cloud storage, returns a presigned/SAS URL.
        """
        ...
