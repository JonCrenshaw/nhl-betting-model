"""Tests for ``puckbunny.ingestion.manifest``.

The manifest is the dedupe primitive that PR-E and PR-G consult before
fetching a payload. These tests pin its read/append round-trip, the
empty-on-first-use behavior, and the
``has(endpoint, scope_key)`` lookup.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from puckbunny.ingestion.manifest import (
    DEFAULT_MANIFEST_KEY,
    ManifestEntry,
    ManifestStore,
    build_entry,
    new_run_id,
)
from puckbunny.storage.local import LocalFilesystemStorage

if TYPE_CHECKING:
    from pathlib import Path


# --------------------------------------------------------------------
# ManifestEntry round-trip
# --------------------------------------------------------------------


def test_manifest_entry_round_trips_through_jsonl() -> None:
    """``to_jsonl_line`` → ``from_jsonl_line`` must be idempotent so a
    written manifest reads back to identical entries."""
    entry = ManifestEntry(
        run_id="abc123",
        endpoint="/v1/gamecenter/{gameId}/landing",
        scope_key="2025030123",
        fetched_at_utc=datetime(2026, 4, 25, 12, 30, 0, tzinfo=UTC),
        rows=1,
        bytes=5700,
        status="ok",
    )
    line = entry.to_jsonl_line()
    assert line.endswith("\n")
    parsed = ManifestEntry.from_jsonl_line(line)
    assert parsed == entry


def test_manifest_entry_serializes_iso_timestamp() -> None:
    """Timestamps must be ISO-8601 strings on disk so external tooling
    (DuckDB, jq, dbt) can read the manifest without a custom decoder."""
    entry = ManifestEntry(
        run_id="r1",
        endpoint="/v1/gamecenter/{gameId}/landing",
        scope_key="2025030123",
        fetched_at_utc=datetime(2026, 4, 25, 12, 30, 0, tzinfo=UTC),
        rows=1,
        bytes=5700,
    )
    payload = json.loads(entry.to_jsonl_line())
    assert payload["fetched_at_utc"] == "2026-04-25T12:30:00+00:00"


def test_new_run_id_is_unique() -> None:
    assert new_run_id() != new_run_id()


# --------------------------------------------------------------------
# ManifestStore — empty / append / read
# --------------------------------------------------------------------


def test_read_entries_returns_empty_when_manifest_does_not_exist(
    tmp_path: Path,
) -> None:
    """First-ever invocation: no manifest object yet, ``read_entries`` is empty."""
    storage = LocalFilesystemStorage(tmp_path)
    store = ManifestStore(storage)
    assert store.read_entries() == []
    # ``has`` on the empty store is always False.
    assert store.has("/v1/gamecenter/{gameId}/landing", "2025030123") is False


def test_append_then_read_round_trip(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    store = ManifestStore(storage)

    entry = build_entry(
        run_id="run-1",
        endpoint="/v1/gamecenter/{gameId}/landing",
        scope_key="2025030123",
        rows=1,
        bytes_written=5700,
    )
    store.append(entry)

    entries = store.read_entries()
    assert len(entries) == 1
    assert entries[0].endpoint == "/v1/gamecenter/{gameId}/landing"
    assert entries[0].scope_key == "2025030123"
    assert entries[0].rows == 1
    assert entries[0].bytes == 5700
    assert entries[0].status == "ok"


def test_append_preserves_existing_entries(tmp_path: Path) -> None:
    """The S3-friendly read-then-write pattern must not clobber prior rows."""
    storage = LocalFilesystemStorage(tmp_path)
    store = ManifestStore(storage)

    e1 = build_entry(
        run_id="r1",
        endpoint="/v1/gamecenter/{gameId}/landing",
        scope_key="2025030123",
        rows=1,
        bytes_written=5700,
    )
    e2 = build_entry(
        run_id="r2",
        endpoint="/v1/gamecenter/{gameId}/boxscore",
        scope_key="2025030123",
        rows=1,
        bytes_written=5500,
    )
    store.append(e1)
    store.append(e2)

    entries = store.read_entries()
    assert [e.endpoint for e in entries] == [
        "/v1/gamecenter/{gameId}/landing",
        "/v1/gamecenter/{gameId}/boxscore",
    ]


def test_append_many_writes_in_one_round_trip(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    store = ManifestStore(storage)

    entries = [
        build_entry(
            run_id="r1",
            endpoint=ep,
            scope_key="2025030123",
            rows=1,
            bytes_written=1000,
        )
        for ep in (
            "/v1/gamecenter/{gameId}/landing",
            "/v1/gamecenter/{gameId}/boxscore",
            "/v1/gamecenter/{gameId}/play-by-play",
        )
    ]
    count = store.append_many(entries)
    assert count == 3
    assert len(store.read_entries()) == 3


def test_append_many_with_empty_iterable_is_a_noop(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    store = ManifestStore(storage)

    count = store.append_many([])
    assert count == 0
    # No object was written — read_entries still empty, no manifest file.
    assert store.read_entries() == []


def test_has_matches_endpoint_and_scope_key(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    store = ManifestStore(storage)

    store.append(
        build_entry(
            run_id="r1",
            endpoint="/v1/gamecenter/{gameId}/landing",
            scope_key="2025030123",
            rows=1,
            bytes_written=5700,
        )
    )

    assert store.has("/v1/gamecenter/{gameId}/landing", "2025030123")
    # Different endpoint, same scope_key — no match.
    assert not store.has("/v1/gamecenter/{gameId}/boxscore", "2025030123")
    # Same endpoint, different scope_key — no match.
    assert not store.has("/v1/gamecenter/{gameId}/landing", "2025030124")


def test_has_ignores_non_ok_status(tmp_path: Path) -> None:
    """Non-``ok`` entries (reserved for PR-G failure logging) must not
    satisfy a dedupe check."""
    storage = LocalFilesystemStorage(tmp_path)
    store = ManifestStore(storage)
    store.append(
        ManifestEntry(
            run_id="r1",
            endpoint="/v1/gamecenter/{gameId}/landing",
            scope_key="2025030123",
            fetched_at_utc=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
            rows=0,
            bytes=0,
            status="error",
        )
    )
    assert not store.has("/v1/gamecenter/{gameId}/landing", "2025030123")


def test_read_entries_skips_blank_lines(tmp_path: Path) -> None:
    """A trailing blank line shouldn't poison reads — defense against
    a partially-flushed write."""
    storage = LocalFilesystemStorage(tmp_path)
    # Hand-write a manifest with a trailing blank line.
    entry = build_entry(
        run_id="r1",
        endpoint="/v1/gamecenter/{gameId}/landing",
        scope_key="2025030123",
        rows=1,
        bytes_written=5700,
    )
    body = (entry.to_jsonl_line() + "\n").encode("utf-8")
    storage.put_object(DEFAULT_MANIFEST_KEY, body)

    store = ManifestStore(storage)
    entries = store.read_entries()
    assert len(entries) == 1


def test_default_manifest_key_lives_under_manifests_prefix() -> None:
    """The bronze partition listings ``bronze/nhl_api/...`` should not
    accidentally pick up the manifest, so it lives under
    ``bronze/_manifests/`` (leading underscore + plural) per D7."""
    assert DEFAULT_MANIFEST_KEY == "bronze/_manifests/ingest_runs.jsonl"


def test_build_entry_uses_utc_now_by_default() -> None:
    """``build_entry`` provides a tz-aware default so callers don't
    have to remember the discipline."""
    entry = build_entry(
        run_id="r1",
        endpoint="/v1/gamecenter/{gameId}/landing",
        scope_key="2025030123",
        rows=1,
        bytes_written=5700,
    )
    assert entry.fetched_at_utc.tzinfo is not None


def test_custom_manifest_key_is_used(tmp_path: Path) -> None:
    """Allow callers to override the key — useful for per-test isolation."""
    storage = LocalFilesystemStorage(tmp_path)
    custom = "test/manifest.jsonl"
    store = ManifestStore(storage, key=custom)
    store.append(
        build_entry(
            run_id="r1",
            endpoint="x",
            scope_key="y",
            rows=0,
            bytes_written=0,
        )
    )
    assert store.key == custom
    # The default-key store must not see this write.
    other = ManifestStore(storage)
    assert other.read_entries() == []


# --------------------------------------------------------------------
# from_jsonl_line — error handling
# --------------------------------------------------------------------


def test_from_jsonl_line_raises_on_missing_required_field() -> None:
    bad = json.dumps({"run_id": "r1"})  # missing everything else
    with pytest.raises(KeyError):
        ManifestEntry.from_jsonl_line(bad)
