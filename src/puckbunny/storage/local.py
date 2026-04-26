"""Local-filesystem object storage backend.

Used by tests to exercise the Parquet writer without hitting R2, and
useful in development for inspecting bronze output by ``ls``-ing a real
directory tree. Object keys map 1:1 to relative paths under ``root``.

Path traversal via ``..`` is rejected to keep the writer's behavior
identical regardless of the supplied key.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from puckbunny.storage.base import ObjectMetadata

if TYPE_CHECKING:
    from collections.abc import Iterator


class LocalFilesystemStorage:
    """``ObjectStorage`` implementation backed by a local directory."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # --- ObjectStorage Protocol ---

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,  # noqa: ARG002 — parity with Protocol
    ) -> None:
        path = self._key_to_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def get_object(self, key: str) -> bytes:
        return self._key_to_path(key).read_bytes()

    def head_object(self, key: str) -> ObjectMetadata:
        path = self._key_to_path(key)
        stat = path.stat()
        return ObjectMetadata(
            key=key,
            size_bytes=stat.st_size,
            etag="",
            content_type=None,
        )

    def list_objects(self, prefix: str) -> Iterator[str]:
        # Empty prefix walks the entire root.
        if prefix == "":
            search_root = self._root
        else:
            search_root = self._key_to_path(prefix)
            # If the prefix names a file directly, yield just that key.
            if search_root.is_file():
                yield prefix
                return
        if not search_root.exists():
            return
        for path in sorted(search_root.rglob("*")):
            if path.is_file():
                yield path.relative_to(self._root).as_posix()

    def delete_object(self, key: str) -> None:
        self._key_to_path(key).unlink(missing_ok=True)

    # --- internals ---

    def _key_to_path(self, key: str) -> Path:
        if not key:
            raise ValueError("key must not be empty")
        candidate = (self._root / key).resolve()
        # ``relative_to`` raises if ``candidate`` is outside ``_root``.
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(f"key escapes storage root: {key!r}") from exc
        return candidate
