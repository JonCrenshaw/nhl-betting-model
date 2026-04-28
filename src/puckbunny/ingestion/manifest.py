"""Append-only ingest manifest for the bronze layer.

D7 in ``docs/milestones/m2-nhl-ingestion.md`` commits the manifest
shape: one JSONL row per ``(endpoint, scope_key)`` successful fetch,
stored at ``bronze/_manifests/ingest_runs.jsonl`` in the same object
storage that holds the bronze Parquet. The two consumers are:

* the daily walker (PR-E) — uses :meth:`ManifestStore.has` to skip
  ``(endpoint, scope_key)`` pairs that already landed in bronze, so
  re-runs of the same date are idempotent;
* the backfill CLI (PR-G) — uses the same primitive to resume after
  interruption without re-fetching everything.

S3 (and therefore R2) doesn't support append, so :meth:`append` reads
the full file, appends in-memory, and writes the full file back. At
M2 scale (~50k entries x ~200 bytes/entry, ~10 MB total), this is
fine; PR-G can revisit if backfill performance becomes a concern.

The module is sport-agnostic: ``endpoint`` is whatever URL template
the loader recorded, ``scope_key`` is whatever string identifies the
unit of work (typically ``str(game_id)`` for game-level endpoints,
``str(season)`` for season-scoped ones in PR-F).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterable

    from puckbunny.storage.base import ObjectStorage


#: Default object key for the manifest. Lives under ``_manifests/`` so
#: ``list_objects("bronze/nhl_api/")`` doesn't accidentally pick it up
#: when downstream tooling iterates bronze partitions.
DEFAULT_MANIFEST_KEY: str = "bronze/_manifests/ingest_runs.jsonl"


@dataclass(frozen=True)
class ManifestEntry:
    """One append to the JSONL manifest.

    Field order matches D7. ``run_id`` is a per-invocation UUID hex so
    a single CLI run's writes can be grouped post-hoc; ``status`` is
    fixed to ``"ok"`` for now (we only record successful writes), but
    is kept as a column so PR-G can surface partial failures without a
    schema change.
    """

    run_id: str
    endpoint: str
    scope_key: str
    fetched_at_utc: datetime
    rows: int
    bytes: int
    status: str = "ok"

    def to_jsonl_line(self) -> str:
        """Serialize as one ``\\n``-terminated JSON line.

        ``fetched_at_utc`` is written as an ISO-8601 string so the file
        round-trips cleanly through any JSONL viewer; the dataclass
        round-trip happens via :meth:`from_jsonl_line` which parses
        the timestamp back.
        """
        payload = asdict(self)
        payload["fetched_at_utc"] = self.fetched_at_utc.isoformat()
        return json.dumps(payload, sort_keys=True) + "\n"

    @classmethod
    def from_jsonl_line(cls, line: str) -> ManifestEntry:
        """Parse one JSONL line back to an entry. Missing keys raise."""
        payload = json.loads(line)
        return cls(
            run_id=str(payload["run_id"]),
            endpoint=str(payload["endpoint"]),
            scope_key=str(payload["scope_key"]),
            fetched_at_utc=datetime.fromisoformat(payload["fetched_at_utc"]),
            rows=int(payload["rows"]),
            bytes=int(payload["bytes"]),
            status=str(payload.get("status", "ok")),
        )


def new_run_id() -> str:
    """Return a fresh ``run_id`` (uuid4 hex). Surfaced as a free function
    so the daily/backfill orchestrators can stamp every manifest entry
    in a given invocation with the same id without holding a manifest
    instance reference."""
    return uuid.uuid4().hex


class ManifestStore:
    """Read/append wrapper over a JSONL manifest in object storage.

    The store re-reads the file on every call. Caching across calls
    would be a footgun in long-running processes (drift between memory
    and storage); at M2's volume the read cost is negligible.
    """

    def __init__(
        self,
        storage: ObjectStorage,
        *,
        key: str = DEFAULT_MANIFEST_KEY,
    ) -> None:
        self._storage = storage
        self._key = key
        self._log = structlog.get_logger(__name__).bind(manifest_key=key)

    @property
    def key(self) -> str:
        return self._key

    # --- public API ---

    def read_entries(self) -> list[ManifestEntry]:
        """Return all entries in the manifest, in file order.

        Returns an empty list if the manifest doesn't exist yet
        (first-ever run). Skips blank lines defensively — a partial
        write that left a trailing empty line shouldn't poison reads.
        """
        body = self._read_raw()
        if not body:
            return []
        text = body.decode("utf-8")
        entries: list[ManifestEntry] = []
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            entries.append(ManifestEntry.from_jsonl_line(stripped))
        return entries

    def has(self, endpoint: str, scope_key: str) -> bool:
        """``True`` iff an ``ok`` entry exists for ``(endpoint, scope_key)``.

        Linear scan of the file. The daily walker calls this once per
        ``(endpoint, game_id)`` pair, so for a typical 12-game day with
        3 endpoints that's 36 scans of an entry list that grows by ≤36
        per day — trivially fast. PR-G's backfill loop will hit this
        ~40k times across a full season; still fine, but if it becomes
        slow we add an in-memory index.
        """
        for entry in self.read_entries():
            if entry.endpoint == endpoint and entry.scope_key == scope_key and entry.status == "ok":
                return True
        return False

    def append(self, entry: ManifestEntry) -> None:
        """Append ``entry`` to the manifest.

        Implemented as read-existing + concatenate + write-back because
        S3 / R2 have no native append. Single-process, single-threaded
        for M2 (per the M2 plan D6); concurrent writers would race
        here, and PR-G is the right place to revisit if M10's Dagster
        wiring ever runs the daily and backfill in parallel.
        """
        existing = self._read_raw()
        new_body = existing + entry.to_jsonl_line().encode("utf-8")
        self._storage.put_object(
            self._key,
            new_body,
            content_type="application/x-ndjson",
        )
        self._log.info(
            "manifest_appended",
            endpoint=entry.endpoint,
            scope_key=entry.scope_key,
            run_id=entry.run_id,
            rows=entry.rows,
            bytes=entry.bytes,
        )

    def append_many(self, entries: Iterable[ManifestEntry]) -> int:
        """Append all ``entries`` in one round-trip. Returns the count
        actually appended.

        The daily walker batches its writes to avoid N+1 PUTs against
        R2 — reading the manifest, materializing the new lines, and
        writing once is one round-trip total instead of N+1.
        """
        new_lines = [e.to_jsonl_line() for e in entries]
        if not new_lines:
            return 0
        existing = self._read_raw()
        new_body = existing + "".join(new_lines).encode("utf-8")
        self._storage.put_object(
            self._key,
            new_body,
            content_type="application/x-ndjson",
        )
        self._log.info("manifest_appended_batch", count=len(new_lines))
        return len(new_lines)

    # --- internals ---

    def _read_raw(self) -> bytes:
        """Return the manifest's raw bytes, or ``b""`` if not yet written.

        Backend-agnostic existence check: ``list_objects`` with the full
        key as prefix yields the key if present and nothing if not.
        Avoids importing :mod:`botocore` here just to catch
        ``NoSuchKey`` on R2 vs ``FileNotFoundError`` on local.
        """
        for found_key in self._storage.list_objects(self._key):
            if found_key == self._key:
                return self._storage.get_object(self._key)
        return b""


def build_entry(
    *,
    run_id: str,
    endpoint: str,
    scope_key: str,
    rows: int,
    bytes_written: int,
    status: str = "ok",
    fetched_at_utc: datetime | None = None,
) -> ManifestEntry:
    """Convenience constructor with a UTC-now default for ``fetched_at_utc``.

    Mirrors :class:`puckbunny.storage.parquet.BronzeEnvelope`'s discipline
    that timestamps in bronze are always tz-aware. The ``bytes_written``
    parameter is named to disambiguate from the builtin ``bytes``.
    """
    return ManifestEntry(
        run_id=run_id,
        endpoint=endpoint,
        scope_key=scope_key,
        fetched_at_utc=fetched_at_utc or datetime.now(UTC),
        rows=rows,
        bytes=bytes_written,
        status=status,
    )
