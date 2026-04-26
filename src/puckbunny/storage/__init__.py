"""Object-storage primitives for the bronze layer.

The storage layer is split into a backend-agnostic Protocol
(:class:`puckbunny.storage.base.ObjectStorage`) plus two concrete
backends: :class:`puckbunny.storage.r2.R2ObjectStorage` for production
(Cloudflare R2 over the S3 API) and
:class:`puckbunny.storage.local.LocalFilesystemStorage` for tests and
offline dev runs.

The typed-envelope Parquet writer in
:mod:`puckbunny.storage.parquet` consumes any ``ObjectStorage`` and is
where the bronze layout (per ``docs/milestones/m2-nhl-ingestion.md``
D2 / D3) is enforced.
"""

from __future__ import annotations

from puckbunny.storage.base import ObjectMetadata, ObjectStorage
from puckbunny.storage.local import LocalFilesystemStorage
from puckbunny.storage.parquet import (
    ENVELOPE_SCHEMA,
    BronzeEnvelope,
    WriteResult,
    build_envelope_table,
    envelope_table_to_parquet_bytes,
    write_envelope_partition,
)
from puckbunny.storage.r2 import R2Credentials, R2ObjectStorage

__all__ = [
    "ENVELOPE_SCHEMA",
    "BronzeEnvelope",
    "LocalFilesystemStorage",
    "ObjectMetadata",
    "ObjectStorage",
    "R2Credentials",
    "R2ObjectStorage",
    "WriteResult",
    "build_envelope_table",
    "envelope_table_to_parquet_bytes",
    "write_envelope_partition",
]
