"""Tests for ``puckbunny.storage.parquet`` — the typed-envelope writer.

We exercise the writer against a ``LocalFilesystemStorage`` target
because the bronze layout (path + schema + zstd-Parquet body) is the
contract — the choice of backend is not. R2-specific behavior is
covered separately in ``tests/storage/test_r2.py``.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from puckbunny.storage.local import LocalFilesystemStorage
from puckbunny.storage.parquet import (
    ENVELOPE_SCHEMA,
    BronzeEnvelope,
    build_envelope_table,
    build_partition_key,
    envelope_table_to_parquet_bytes,
    write_envelope_partition,
)


def _make_envelope(**overrides) -> BronzeEnvelope:
    base = {
        "entity_id": "2025030123",
        "endpoint": "/v1/gamecenter/{gameId}/landing",
        "endpoint_params": {"gameId": 2025030123},
        "fetched_at_utc": datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC),
        "response_json": json.dumps({"id": 2025030123, "season": "20252026"}),
        "season": "20252026",
        "event_date": date(2026, 4, 24),
    }
    base.update(overrides)
    return BronzeEnvelope(**base)


def test_envelope_auto_computes_sha256() -> None:
    env = _make_envelope()
    expected = hashlib.sha256(env.response_json.encode("utf-8")).hexdigest()
    assert env.response_sha256 == expected


def test_envelope_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _make_envelope(fetched_at_utc=datetime(2026, 4, 25, 12, 0, 0))


def test_build_envelope_table_matches_schema() -> None:
    table = build_envelope_table([_make_envelope(), _make_envelope(entity_id="2025030124")])
    assert table.schema.equals(ENVELOPE_SCHEMA)
    assert table.num_rows == 2


def test_build_envelope_table_rejects_empty() -> None:
    with pytest.raises(ValueError):
        build_envelope_table([])


def test_envelope_round_trip_via_local_storage(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    rows = [
        _make_envelope(entity_id="2025030123"),
        _make_envelope(
            entity_id="2025030124",
            response_json=json.dumps({"id": 2025030124}),
        ),
    ]
    result = write_envelope_partition(
        storage,
        rows,
        base_prefix="bronze/nhl_api",
        endpoint_name="landing",
        ingest_date=date(2026, 4, 25),
        file_id="abc123",
    )

    assert result.rows == 2
    assert result.bytes > 0
    assert result.key == ("bronze/nhl_api/landing/ingest_date=2026-04-25/abc123.parquet")

    # File materialized under the local root.
    on_disk = tmp_path / "bronze/nhl_api/landing/ingest_date=2026-04-25/abc123.parquet"
    assert on_disk.exists()

    # Re-open and confirm schema + values.
    table = pq.read_table(io.BytesIO(on_disk.read_bytes()))
    assert table.schema.equals(ENVELOPE_SCHEMA)
    assert table.num_rows == 2
    assert table.column("entity_id").to_pylist() == ["2025030123", "2025030124"]
    assert table.column("season").to_pylist() == ["20252026", "20252026"]
    fetched = table.column("fetched_at_utc").to_pylist()
    assert all(d.tzinfo is not None for d in fetched)


def test_build_partition_key_layout() -> None:
    key = build_partition_key(
        base_prefix="bronze/nhl_api/",  # trailing slash is tolerated
        endpoint_name="play-by-play",
        ingest_date=date(2026, 4, 25),
        file_id="run-001",
    )
    assert key == "bronze/nhl_api/play-by-play/ingest_date=2026-04-25/run-001.parquet"


def test_zstd_compression_actually_compresses() -> None:
    # Repeated content compresses well; verify the writer is using zstd.
    big_response = json.dumps({"plays": [{"k": "v"} for _ in range(2000)]})
    rows = [_make_envelope(response_json=big_response)]
    table = build_envelope_table(rows)
    body = envelope_table_to_parquet_bytes(table)
    # Parquet header + footer overhead but body is highly compressible.
    assert len(body) < len(big_response) // 2


def test_default_file_id_is_unique(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    a = write_envelope_partition(
        storage,
        [_make_envelope()],
        base_prefix="bronze/nhl_api",
        endpoint_name="landing",
        ingest_date=date(2026, 4, 25),
    )
    b = write_envelope_partition(
        storage,
        [_make_envelope()],
        base_prefix="bronze/nhl_api",
        endpoint_name="landing",
        ingest_date=date(2026, 4, 25),
    )
    assert a.key != b.key
