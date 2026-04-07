"""Local filesystem storage backend.

Stores files under a configurable base directory with tenant isolation.
Suitable for development and single-server deployments. For production
multi-server deployments, use S3 or similar cloud storage.
"""

import os
import uuid
from pathlib import Path

from src.core.storage.base import StorageBackend, StoredFile


class LocalStorageBackend(StorageBackend):
    """Store files on the local filesystem."""

    def __init__(self, base_dir: str = "storage") -> None:
        self.base_dir = Path(base_dir)

    def _resolve_path(self, folder: str, filename: str, tenant_id: str | None) -> Path:
        """Build the full path with tenant isolation."""
        if tenant_id:
            return self.base_dir / f"tenants/{tenant_id}/{folder}/{filename}"
        return self.base_dir / f"shared/{folder}/{filename}"

    def _safe_filename(self, filename: str) -> str:
        """Generate a unique filename to prevent collisions and path traversal."""
        # Strip path components to prevent directory traversal
        clean = os.path.basename(filename)
        stem, ext = os.path.splitext(clean)
        return f"{stem}_{uuid.uuid4().hex[:8]}{ext}"

    async def save(
        self,
        folder: str,
        filename: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        tenant_id: str | None = None,
    ) -> StoredFile:
        safe_name = self._safe_filename(filename)
        full_path = self._resolve_path(folder, safe_name, tenant_id)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)

        return StoredFile(
            path=str(full_path),
            filename=safe_name,
            content_type=content_type,
            size=len(content),
            tenant_id=tenant_id,
        )

    async def read(self, path: str) -> bytes:
        return Path(path).read_bytes()

    async def delete(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            p.unlink()

    async def exists(self, path: str) -> bool:
        return Path(path).exists()

    async def get_url(self, path: str, *, expires_in: int = 3600) -> str:
        return f"/files/{path}"
