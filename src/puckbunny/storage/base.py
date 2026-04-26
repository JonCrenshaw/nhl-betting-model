"""Backend-agnostic object-storage Protocol.

Concrete implementations live in :mod:`puckbunny.storage.r2` (Cloudflare
R2 via boto3) and :mod:`puckbunny.storage.local`. Tests substitute the
local backend so the Parquet writer can be exercised without hitting R2.

The surface area is intentionally minimal: bronze ingestion only needs
``put`` / ``get`` / ``head`` / ``list`` / ``delete``. Anything fancier
(streaming uploads, multipart, presigned URLs) is added when a caller
actually needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(frozen=True)
class ObjectMetadata:
    """Lightweight metadata snapshot for an object."""

    key: str
    size_bytes: int
    etag: str
    content_type: str | None


@runtime_checkable
class ObjectStorage(Protocol):
    """Contract implemented by R2 and local-filesystem backends."""

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        """Write ``body`` at ``key``. Overwrites any existing object."""

    def get_object(self, key: str) -> bytes:
        """Read and return the full object at ``key``."""

    def head_object(self, key: str) -> ObjectMetadata:
        """Return metadata for ``key`` without downloading the body."""

    def list_objects(self, prefix: str) -> Iterator[str]:
        """Yield keys under ``prefix`` in lexicographic order."""

    def delete_object(self, key: str) -> None:
        """Delete the object at ``key``. No error if it does not exist."""
