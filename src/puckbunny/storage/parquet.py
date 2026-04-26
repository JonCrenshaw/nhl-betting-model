"""Typed-envelope Parquet writer for the bronze layer.

The "typed envelope plus raw JSON" row shape is documented in
``docs/milestones/m2-nhl-ingestion.md`` D3. Per-row columns:

==========================  ==========================  ============================================
Column                      Type                        Purpose
==========================  ==========================  ============================================
``entity_id``               ``string`` (required)       Natural key from the payload (e.g.
                                                        ``str(response["id"])`` for a game).
``season``                  ``string`` (nullable)       Season string, e.g. ``"20252026"``.
``event_date``              ``date32`` (nullable)       Event date — *not* ingest date.
``endpoint``                ``string`` (required)       URL template that produced the row.
``endpoint_params_json``    ``string`` (required)       The exact parameter dict used, as JSON.
``fetched_at_utc``          ``timestamp[us, UTC]``      When we called the API.
``response_json``           ``large_string``            Verbatim API response body.
``response_sha256``         ``string`` (required)       Dedupe key for idempotent re-runs.
==========================  ==========================  ============================================

The schema is pinned. Adding columns is a breaking bronze change; let
the silver layer (M3) reconcile new fields out of ``response_json``
instead.

Compression defaults to ``zstd`` level 3, which the PR-A spike measured
at ~8x for play-by-play payloads (the largest per-game endpoint).
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime

    from puckbunny.storage.base import ObjectStorage

#: Pyarrow schema for the bronze typed envelope. See module docstring.
ENVELOPE_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("season", pa.string(), nullable=True),
        pa.field("event_date", pa.date32(), nullable=True),
        pa.field("endpoint", pa.string(), nullable=False),
        pa.field("endpoint_params_json", pa.string(), nullable=False),
        pa.field("fetched_at_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("response_json", pa.large_string(), nullable=False),
        pa.field("response_sha256", pa.string(), nullable=False),
    ]
)


@dataclass(frozen=True)
class BronzeEnvelope:
    """One row of bronze typed-envelope data.

    ``response_sha256`` is computed automatically from ``response_json``
    if not supplied. ``fetched_at_utc`` must be timezone-aware; this is a
    deliberate guardrail — naive timestamps in bronze are a bug.
    """

    entity_id: str
    endpoint: str
    endpoint_params: Mapping[str, Any]
    fetched_at_utc: datetime
    response_json: str
    season: str | None = None
    event_date: date | None = None
    response_sha256: str = field(default="")

    def __post_init__(self) -> None:
        if self.fetched_at_utc.tzinfo is None:
            raise ValueError(
                "fetched_at_utc must be timezone-aware (UTC). "
                "Naive datetimes are a bronze-layer bug."
            )
        if not self.response_sha256:
            digest = hashlib.sha256(self.response_json.encode("utf-8")).hexdigest()
            object.__setattr__(self, "response_sha256", digest)


@dataclass(frozen=True)
class WriteResult:
    """Summary returned by :func:`write_envelope_partition`."""

    key: str
    rows: int
    bytes: int


def build_envelope_table(rows: Sequence[BronzeEnvelope]) -> pa.Table:
    """Convert envelopes to a pyarrow Table matching :data:`ENVELOPE_SCHEMA`."""
    if not rows:
        raise ValueError("rows must be non-empty")

    entity_ids: list[str] = []
    seasons: list[str | None] = []
    event_dates: list[date | None] = []
    endpoints: list[str] = []
    params_json: list[str] = []
    fetched_at: list[datetime] = []
    response_json: list[str] = []
    response_sha256: list[str] = []

    for r in rows:
        entity_ids.append(r.entity_id)
        seasons.append(r.season)
        event_dates.append(r.event_date)
        endpoints.append(r.endpoint)
        # ``sort_keys=True`` so identical params produce identical bytes
        # — useful for response_sha256 + dedupe equivalence later.
        params_json.append(json.dumps(dict(r.endpoint_params), sort_keys=True, default=str))
        fetched_at.append(r.fetched_at_utc)
        response_json.append(r.response_json)
        response_sha256.append(r.response_sha256)

    return pa.table(
        {
            "entity_id": entity_ids,
            "season": seasons,
            "event_date": event_dates,
            "endpoint": endpoints,
            "endpoint_params_json": params_json,
            "fetched_at_utc": fetched_at,
            "response_json": response_json,
            "response_sha256": response_sha256,
        },
        schema=ENVELOPE_SCHEMA,
    )


def envelope_table_to_parquet_bytes(
    table: pa.Table,
    *,
    compression: str = "zstd",
    compression_level: int = 3,
) -> bytes:
    """Serialize ``table`` to in-memory Parquet bytes.

    zstd-3 was measured at ~8x compression on play-by-play payloads in
    the PR-A spike (see ``docs/ideas/pra-spike-notes.md`` storage table).
    Higher levels offer marginal extra compression at meaningful CPU
    cost; not worth it at our volumes.
    """
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression=compression,
        compression_level=compression_level,
    )
    return buf.getvalue()


def build_partition_key(
    *,
    base_prefix: str,
    endpoint_name: str,
    ingest_date: date,
    file_id: str,
) -> str:
    """Compose the bronze object key per M2 D2 layout.

    Pattern: ``{base_prefix}/{endpoint_name}/ingest_date=YYYY-MM-DD/{file_id}.parquet``.
    """
    return (
        f"{base_prefix.rstrip('/')}"
        f"/{endpoint_name}"
        f"/ingest_date={ingest_date.isoformat()}"
        f"/{file_id}.parquet"
    )


def write_envelope_partition(
    storage: ObjectStorage,
    rows: Sequence[BronzeEnvelope],
    *,
    base_prefix: str,
    endpoint_name: str,
    ingest_date: date,
    file_id: str | None = None,
) -> WriteResult:
    """Write one Parquet file at the canonical bronze partition path.

    Path: ``{base_prefix}/{endpoint_name}/ingest_date=YYYY-MM-DD/{file_id}.parquet``.

    A random ``uuid4`` hex is used for ``file_id`` if not supplied —
    callers backfilling deterministically should pass an explicit ID
    (e.g., a manifest run-id) so re-runs overwrite the same key.
    """
    table = build_envelope_table(rows)
    body = envelope_table_to_parquet_bytes(table)
    fid = file_id or uuid.uuid4().hex
    key = build_partition_key(
        base_prefix=base_prefix,
        endpoint_name=endpoint_name,
        ingest_date=ingest_date,
        file_id=fid,
    )
    storage.put_object(key, body, content_type="application/vnd.apache.parquet")
    return WriteResult(key=key, rows=len(rows), bytes=len(body))
