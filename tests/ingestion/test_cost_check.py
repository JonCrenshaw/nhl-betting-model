"""Tests for :mod:`puckbunny.ingestion.cost_check`.

Covers the projection arithmetic in isolation (no real R2, no real
manifest contents — synthesize entries directly), the env-var
threshold override, and the three ``--cost-check`` modes the backfill
orchestrator will pass to :func:`evaluate`.

A :class:`puckbunny.storage.local.LocalFilesystemStorage` under
``tmp_path`` backs the :class:`ManifestStore`; we go through the real
manifest I/O path so the test catches drift between manifest schema
changes and cost-check assumptions about the ``bytes`` column.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from puckbunny.ingestion.cost_check import (
    COST_CHECK_THRESHOLD_USD,
    R2_STORAGE_USD_PER_GB_MONTH,
    THRESHOLD_ENV_VAR,
    CostCheckTripped,
    CostProjection,
    compute_projection,
    evaluate,
    resolve_threshold_usd,
)
from puckbunny.ingestion.manifest import ManifestEntry, ManifestStore
from puckbunny.storage.local import LocalFilesystemStorage

if TYPE_CHECKING:
    from pathlib import Path


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _entry(*, bytes_written: int, run_id: str = "test-run", scope: str = "1") -> ManifestEntry:
    """Build a synthetic ManifestEntry with everything but ``bytes`` held
    constant. The cost-check projection only reads ``bytes``; the rest
    is filler so the JSONL round-trip is well-formed."""
    return ManifestEntry(
        run_id=run_id,
        endpoint="/v1/test",
        scope_key=scope,
        fetched_at_utc=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        rows=1,
        bytes=bytes_written,
        status="ok",
    )


def _make_manifest(tmp_path: Path, entries: list[ManifestEntry]) -> ManifestStore:
    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)
    if entries:
        manifest.append_many(entries)
    return manifest


# --------------------------------------------------------------------
# resolve_threshold_usd
# --------------------------------------------------------------------


def test_resolve_threshold_usd_default_when_env_unset() -> None:
    assert resolve_threshold_usd(env={}) == COST_CHECK_THRESHOLD_USD


def test_resolve_threshold_usd_default_when_env_blank() -> None:
    """Empty string in the env var falls back to the default (some
    shells set empty rather than unset)."""
    assert resolve_threshold_usd(env={THRESHOLD_ENV_VAR: ""}) == COST_CHECK_THRESHOLD_USD


def test_resolve_threshold_usd_uses_env_override() -> None:
    assert resolve_threshold_usd(env={THRESHOLD_ENV_VAR: "10.00"}) == 10.00


def test_resolve_threshold_usd_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="not a valid USD amount"):
        resolve_threshold_usd(env={THRESHOLD_ENV_VAR: "ten dollars"})


def test_resolve_threshold_usd_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        resolve_threshold_usd(env={THRESHOLD_ENV_VAR: "-1.00"})


def test_resolve_threshold_usd_default_param_takes_effect() -> None:
    """An explicit ``default`` argument overrides the module-level
    constant — used by tests that want a deterministic baseline."""
    assert resolve_threshold_usd(env={}, default=99.99) == 99.99


# --------------------------------------------------------------------
# compute_projection
# --------------------------------------------------------------------


def test_compute_projection_empty_manifest(tmp_path: Path) -> None:
    """A fresh manifest projects to zero cost across the board."""
    manifest = _make_manifest(tmp_path, [])
    projection = compute_projection(manifest, run_id="r1", threshold_usd=5.00)
    assert projection.bytes_cumulative == 0
    assert projection.gigabytes_cumulative == 0.0
    assert projection.monthly_cost_usd == 0.0
    assert projection.tripped is False
    assert projection.run_id == "r1"
    assert projection.threshold_usd == 5.00


def test_compute_projection_sums_all_entries(tmp_path: Path) -> None:
    """``bytes_cumulative`` is the sum across every entry, including
    entries written by previous runs."""
    manifest = _make_manifest(
        tmp_path,
        [
            _entry(bytes_written=1_000, scope="1"),
            _entry(bytes_written=2_000, scope="2"),
            _entry(bytes_written=3_000, scope="3"),
        ],
    )
    projection = compute_projection(manifest, run_id="r1", threshold_usd=5.00)
    assert projection.bytes_cumulative == 6_000


def test_compute_projection_arithmetic_one_gigabyte(tmp_path: Path) -> None:
    """One GB → exactly the R2 monthly storage rate."""
    one_gb = 1024**3
    manifest = _make_manifest(tmp_path, [_entry(bytes_written=one_gb)])
    projection = compute_projection(manifest, run_id="r1", threshold_usd=100.00)
    assert projection.gigabytes_cumulative == pytest.approx(1.0)
    assert projection.monthly_cost_usd == pytest.approx(R2_STORAGE_USD_PER_GB_MONTH)


def test_compute_projection_realistic_backfill_scale(tmp_path: Path) -> None:
    """Sanity-check against Risk #4's measured numbers: ~370 MB full
    backfill projects to roughly $0.0054/month, three orders of
    magnitude inside the $5 default threshold."""
    bytes_370_mb = 370 * 1024 * 1024
    manifest = _make_manifest(tmp_path, [_entry(bytes_written=bytes_370_mb)])
    projection = compute_projection(manifest, run_id="r1", threshold_usd=5.00)
    assert projection.monthly_cost_usd < 0.01
    assert projection.tripped is False


def test_compute_projection_uses_env_when_threshold_kw_omitted(tmp_path: Path) -> None:
    """No explicit ``threshold_usd`` → the env override path runs."""
    manifest = _make_manifest(tmp_path, [_entry(bytes_written=1024**3)])
    projection = compute_projection(
        manifest,
        run_id="r1",
        env={THRESHOLD_ENV_VAR: "0.001"},
    )
    assert projection.threshold_usd == 0.001
    # 1 GB at $0.015/mo > $0.001 threshold → tripped.
    assert projection.tripped is True


def test_compute_projection_explicit_threshold_overrides_env(tmp_path: Path) -> None:
    """A non-None ``threshold_usd`` short-circuits env resolution —
    tests can assert deterministic threshold behavior without a fake
    env."""
    manifest = _make_manifest(tmp_path, [])
    projection = compute_projection(
        manifest,
        run_id="r1",
        threshold_usd=5.00,
        env={THRESHOLD_ENV_VAR: "0.001"},
    )
    assert projection.threshold_usd == 5.00


# --------------------------------------------------------------------
# CostProjection.tripped
# --------------------------------------------------------------------


def test_tripped_strict_greater_than() -> None:
    """A projection that lands *exactly* on the threshold doesn't
    trip; only strictly above does."""
    proj = CostProjection(
        run_id="r1",
        bytes_cumulative=1,
        gigabytes_cumulative=0.0,
        monthly_cost_usd=5.00,
        threshold_usd=5.00,
    )
    assert proj.tripped is False


def test_tripped_above_threshold() -> None:
    proj = CostProjection(
        run_id="r1",
        bytes_cumulative=1,
        gigabytes_cumulative=0.0,
        monthly_cost_usd=5.01,
        threshold_usd=5.00,
    )
    assert proj.tripped is True


# --------------------------------------------------------------------
# evaluate
# --------------------------------------------------------------------


def _untripped_projection() -> CostProjection:
    return CostProjection(
        run_id="r1",
        bytes_cumulative=100,
        gigabytes_cumulative=0.0,
        monthly_cost_usd=0.001,
        threshold_usd=5.00,
    )


def _tripped_projection() -> CostProjection:
    return CostProjection(
        run_id="r1",
        bytes_cumulative=10**12,
        gigabytes_cumulative=931.32,
        monthly_cost_usd=13.97,
        threshold_usd=5.00,
    )


def test_evaluate_fail_untripped_returns() -> None:
    evaluate(_untripped_projection(), "fail")  # no raise


def test_evaluate_fail_tripped_raises() -> None:
    proj = _tripped_projection()
    with pytest.raises(CostCheckTripped) as exc_info:
        evaluate(proj, "fail")
    # The exception carries the projection so callers don't re-compute.
    assert exc_info.value.projection is proj
    # Message includes the projected cost and the threshold for ops.
    msg = str(exc_info.value)
    assert "13.97" in msg
    assert "5.00" in msg
    assert "r1" in msg


def test_evaluate_warn_tripped_returns_without_raising() -> None:
    evaluate(_tripped_projection(), "warn")  # no raise


def test_evaluate_warn_untripped_returns() -> None:
    evaluate(_untripped_projection(), "warn")


def test_evaluate_off_tripped_returns_without_raising() -> None:
    """``off`` ignores the trip; the orchestrator continues."""
    evaluate(_tripped_projection(), "off")


def test_evaluate_off_untripped_returns() -> None:
    evaluate(_untripped_projection(), "off")


def test_evaluate_unknown_mode_raises_value_error() -> None:
    """Defense in depth — argparse should reject anything else, but if
    a caller bypasses the CLI we still want a clear failure."""
    with pytest.raises(ValueError, match="unknown cost-check mode"):
        evaluate(_untripped_projection(), "explode")  # type: ignore[arg-type]
