"""Storage-cost projection + threshold tripwire for ingestion runs.

Per D10 in ``docs/milestones/m2-nhl-ingestion.md``: at the end of each
backfill phase, the orchestrator computes a monthly storage-cost
projection from the cumulative manifest and decides whether to abort
before the next phase. The default threshold is **$5/month**, three
orders of magnitude inside the M2 plan's $50/month operational
ceiling — measured backfill scale projects to ~$0.005/month, so the
``fail`` default behaves as a tripwire (a real surprise like an
uncompressed dump or a runaway loop trips it loudly), not a brake on
expected work.

Storage-only by design (Risk #4 in the M2 plan):

* R2 egress is **zero** for our access pattern (Cloudflare's pricing
  hook), so it doesn't appear in the projection.
* Class A op cost is **one-time and bounded** (one PUT per bronze
  partition write; ~$0.20 across the entire backfill per Risk #4),
  so amortizing it into a per-month projection would distort the
  number more than it'd inform a budget decision.

Sport-agnostic: this module sits one level above ``nhl/`` because R2
cost arithmetic is the same for any future sport's bronze content. A
Phase 3 MLB or NBA loader gets the same primitive for free.

Operational tuning. The threshold is overridable via the
``INGEST_COST_CHECK_THRESHOLD_USD`` env var so an operator running a
deliberate large-scale backfill can raise the gate without a code
change. The env var is resolved at *evaluation* time, not import
time, so monkeypatched values take effect inside a single test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import structlog

if TYPE_CHECKING:
    from puckbunny.ingestion.manifest import ManifestStore

#: Default monthly storage-cost ceiling, in USD. Overridable via the
#: ``INGEST_COST_CHECK_THRESHOLD_USD`` env var. A tripwire, not a
#: brake — measured backfill scale lands ~$0.005/month, so a trip
#: indicates a real surprise (payload explosion, runaway loop,
#: uncompressed dump) rather than a budget call.
COST_CHECK_THRESHOLD_USD: float = 5.00

#: Cloudflare R2 standard storage rate (USD per GB per month). Source:
#: ADR-0001 "Warehouse stack" — R2 was chosen partly because of this
#: rate plus zero egress. If R2 changes the number, update here and
#: the linked ADR; no other file should re-derive this constant.
R2_STORAGE_USD_PER_GB_MONTH: float = 0.015

#: Env-var override key for :data:`COST_CHECK_THRESHOLD_USD`. Surfaced
#: as a constant so the resolution code and the milestone doc stay in
#: sync if it ever needs renaming.
THRESHOLD_ENV_VAR: str = "INGEST_COST_CHECK_THRESHOLD_USD"

#: Cost-check behavior modes. ``fail`` aborts the orchestrator on a
#: trip, ``warn`` logs at WARNING and continues, ``off`` skips the
#: threshold action entirely (the projection is still logged for
#: operator visibility).
CostCheckMode = Literal["fail", "warn", "off"]


class CostCheckTripped(RuntimeError):
    """Raised by :func:`evaluate` when the projection exceeds the
    threshold and the mode is ``"fail"``.

    Subclasses :class:`RuntimeError` rather than :class:`ValueError`
    because the trip is a runtime cost-control decision, not an input
    validation failure. Captures the projection on the instance so a
    caller catching this can render it without re-computing.
    """

    def __init__(self, projection: CostProjection) -> None:
        super().__init__(
            f"cost-check tripped: projected ${projection.monthly_cost_usd:.4f}/mo "
            f"exceeds threshold ${projection.threshold_usd:.2f}/mo "
            f"(bytes_cumulative={projection.bytes_cumulative}, "
            f"run_id={projection.run_id})"
        )
        self.projection = projection


@dataclass(frozen=True)
class CostProjection:
    """One snapshot of cumulative bronze storage and its projected cost.

    The projection is end-of-phase by convention (backfill orchestrator
    calls :func:`compute_projection` after each phase finishes). The
    fields are deliberately denormalized — both ``bytes_cumulative``
    and ``gigabytes_cumulative`` are stored even though one is
    derivable from the other — so structured log lines and downstream
    reports don't have to re-derive at the read site.
    """

    run_id: str
    bytes_cumulative: int
    gigabytes_cumulative: float
    monthly_cost_usd: float
    threshold_usd: float

    @property
    def tripped(self) -> bool:
        """``True`` iff ``monthly_cost_usd`` exceeds ``threshold_usd``.

        Strict ``>`` (not ``>=``) so a projection that lands exactly on
        the threshold doesn't trip — the threshold is a wall, not a
        landing zone. Trivially edge-case-y, kept consistent with how
        the milestone doc phrases the rule ("aborts above $5/mo").
        """
        return self.monthly_cost_usd > self.threshold_usd


def resolve_threshold_usd(
    *,
    env: dict[str, str] | None = None,
    default: float = COST_CHECK_THRESHOLD_USD,
) -> float:
    """Return the active monthly threshold in USD.

    Reads :data:`THRESHOLD_ENV_VAR` from ``env`` (defaults to
    :data:`os.environ`); if unset or non-numeric, falls back to
    ``default``. The env arg is exposed so tests can pass a fake env
    without monkeypatching :mod:`os.environ` — keeps the projection
    deterministic in unit tests.
    """
    source = env if env is not None else os.environ
    raw = source.get(THRESHOLD_ENV_VAR)
    if raw is None or raw == "":
        return default
    try:
        parsed = float(raw)
    except ValueError:
        # Defensive: a malformed env value should fail loud, not
        # silently use the default — operators set this expecting it
        # to take effect.
        raise ValueError(
            f"{THRESHOLD_ENV_VAR}={raw!r} is not a valid USD amount; "
            f"set it to a number like '10.00' or unset to use the "
            f"default ${default:.2f}/mo"
        ) from None
    if parsed < 0:
        raise ValueError(f"{THRESHOLD_ENV_VAR}={raw!r} must be non-negative")
    return parsed


def compute_projection(
    manifest: ManifestStore,
    *,
    run_id: str,
    threshold_usd: float | None = None,
    env: dict[str, str] | None = None,
) -> CostProjection:
    """Read the manifest and project cumulative monthly storage cost.

    Args:
        manifest: The store to read entries from. Sums the ``bytes``
            column across **all** entries — this is the cumulative
            view, not just this run's contribution. The manifest is
            authoritative because every bronze write goes through a
            manifest-recording code path; orphan partitions from
            partial failures don't appear, but the doc explicitly
            accepts that as a tripwire-not-meter tradeoff.
        run_id: The current orchestrator run's id, recorded on the
            projection so log analyzers can group "this backfill's
            cost-check lines" together.
        threshold_usd: Override the threshold. Production callers leave
            this unset and let :func:`resolve_threshold_usd` decide
            (env var or default); tests pass an explicit value to keep
            assertions deterministic.
        env: Override the env source for threshold resolution. Tests
            pass a fake mapping; production leaves unset.

    Returns:
        A :class:`CostProjection` with both the raw bytes and the
        derived cost numbers, plus the active threshold so a downstream
        log line is self-describing.
    """
    threshold = threshold_usd if threshold_usd is not None else resolve_threshold_usd(env=env)
    entries = manifest.read_entries()
    bytes_cumulative = sum(int(e.bytes) for e in entries)
    gigabytes_cumulative = bytes_cumulative / (1024**3)
    monthly_cost_usd = gigabytes_cumulative * R2_STORAGE_USD_PER_GB_MONTH
    return CostProjection(
        run_id=run_id,
        bytes_cumulative=bytes_cumulative,
        gigabytes_cumulative=gigabytes_cumulative,
        monthly_cost_usd=monthly_cost_usd,
        threshold_usd=threshold,
    )


def evaluate(projection: CostProjection, mode: CostCheckMode) -> None:
    """Log the projection and act on a trip per ``mode``.

    Behavior matrix:

    +-----------+--------+----------------------------------------------+
    | mode      | tripped| action                                       |
    +===========+========+==============================================+
    | ``fail``  | False  | INFO log line; return                        |
    +-----------+--------+----------------------------------------------+
    | ``fail``  | True   | ERROR log line; raise :class:`CostCheckTripped` |
    +-----------+--------+----------------------------------------------+
    | ``warn``  | False  | INFO log line; return                        |
    +-----------+--------+----------------------------------------------+
    | ``warn``  | True   | WARNING log line; return                     |
    +-----------+--------+----------------------------------------------+
    | ``off``   | any    | INFO log line (always); return               |
    +-----------+--------+----------------------------------------------+

    The INFO line emits on every untripped check so operators can chart
    storage growth from the structured-log stream — the cost-check
    isn't only useful when it trips. Field names are stable
    (``cost_check``, ``cost_check_tripped``, ``cost_check_tripped_warn``)
    so log queries don't break on a mode change.

    Raises:
        CostCheckTripped: When ``mode == "fail"`` and the projection
            exceeded the threshold. The orchestrator catches this at
            the phase boundary so partial work is never silently
            discarded.
    """
    log = structlog.get_logger(__name__).bind(
        run_id=projection.run_id,
        bytes_cumulative=projection.bytes_cumulative,
        gigabytes_cumulative=round(projection.gigabytes_cumulative, 6),
        monthly_cost_usd=round(projection.monthly_cost_usd, 6),
        threshold_usd=projection.threshold_usd,
        tripped=projection.tripped,
        mode=mode,
    )

    if not projection.tripped:
        log.info("cost_check")
        return

    # Tripped — branch on mode.
    if mode == "fail":
        log.error("cost_check_tripped")
        raise CostCheckTripped(projection)
    if mode == "warn":
        log.warning("cost_check_tripped_warn")
        return
    if mode == "off":
        # ``off`` ignores the trip but still emits the INFO line so the
        # operator can see the projection in logs. The "tripped=True"
        # field on the structured event makes it grep-able for after-
        # the-fact review.
        log.info("cost_check")
        return

    # Defense in depth: argparse `choices=` should have rejected any
    # other value before we get here.
    raise ValueError(f"unknown cost-check mode: {mode!r}")


__all__ = [
    "COST_CHECK_THRESHOLD_USD",
    "R2_STORAGE_USD_PER_GB_MONTH",
    "THRESHOLD_ENV_VAR",
    "CostCheckMode",
    "CostCheckTripped",
    "CostProjection",
    "compute_projection",
    "evaluate",
    "resolve_threshold_usd",
]
