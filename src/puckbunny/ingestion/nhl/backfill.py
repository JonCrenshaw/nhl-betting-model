"""Backfill orchestrator: ingest historical NHL data across seasons.

Per PR-G in ``docs/milestones/m2-nhl-ingestion.md``. Composes the three
season-scoped + game-level loaders into one driver:

* **Three phase functions** (``backfill_team_season``,
  ``backfill_season_summaries``, ``backfill_games``), each iterating
  its own scope units and gating via ``manifest.has(...)`` per the D11
  table.
* **Phase order when ``--loader=all``** is **team-season →
  season-summaries → games**, so the cheap, low-volume phases fail
  fast before burning hours on game-level fetches (D9).
* **End-of-phase cost-check** projects cumulative bronze storage and
  aborts before the next phase if the projection exceeds the active
  threshold (D10). Per Q2 of the PR-G planning, no separate
  end-of-overall pass — the last phase's check IS the end-of-overall.
* **One ``run_id``** is threaded through every loader call so the
  manifest carries a single identifier across the whole backfill —
  "show me what this run wrote" is one ``grep run_id=...`` against
  the JSONL.

Idempotency follows PR-E's per-scope-unit dedupe pattern (D11): if all
endpoint manifest entries for a scope unit are present, skip; if any
are missing, re-fetch all of them. Per-endpoint dedupe was considered
and rejected — it would diverge daily and backfill behavior on partial
failures, force partial-load methods on each loader, and the absolute
saved cost is in the noise.

The orchestrator owns gating for ``team-season`` and ``season-summaries``
but not for ``games``: :class:`DailyLoader.load_date` already gates
per-game and writes its own manifest entries. Pulling that out into the
orchestrator would duplicate logic and split the daily-vs-backfill
behavior on the same idempotency primitive. So the games phase here is
just "for date in window: ``daily_loader.load_date(date, run_id=...)``".

Error policy. Loader-level exceptions (HTTP, schema validation,
mismatched response invariants) propagate; the orchestrator does not
catch generic exceptions. Two consequences worth calling out:

* A mid-flight failure aborts the backfill at that point. The manifest
  captures every successful write up to the failure, so resuming is a
  re-invocation of the same CLI — the per-scope-unit gating skips
  everything already done.
* The 404 case on ``team-season`` is handled inside the loader (returns
  ``None`` for that endpoint) and is **not** treated as an error here:
  the orchestrator writes manifest entries only for the non-``None``
  endpoints and moves on. Subsequent runs re-attempt the 404'd
  endpoint, bounded by ``team_abbrevs`` (one wasted fetch per invalid
  pair per run; explicitly accepted in D11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from puckbunny.ingestion.cost_check import (
    CostCheckTripped,
    compute_projection,
)
from puckbunny.ingestion.cost_check import (
    evaluate as evaluate_cost_check,
)
from puckbunny.ingestion.manifest import (
    build_entry,
    new_run_id,
)
from puckbunny.ingestion.nhl.endpoints import (
    CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
    GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
    ROSTER_ENDPOINT_TEMPLATE,
    SKATER_SUMMARY_ENDPOINT_TEMPLATE,
    TEAM_SUMMARY_ENDPOINT_TEMPLATE,
    dates_in_season,
    format_season_id,
    team_abbrevs,
)

if TYPE_CHECKING:
    from datetime import date

    from puckbunny.ingestion.cost_check import CostCheckMode
    from puckbunny.ingestion.manifest import ManifestEntry, ManifestStore
    from puckbunny.ingestion.nhl.schedule import DailyLoader
    from puckbunny.ingestion.nhl.season_summaries import SeasonSummariesLoader
    from puckbunny.ingestion.nhl.team_season import TeamSeasonLoader


# Endpoint sets used both by the gating logic and by anyone reading
# the orchestrator (and by the tests) to enumerate which endpoints
# define "fully loaded" for a given scope unit.
_TEAM_SEASON_ENDPOINTS: tuple[str, ...] = (
    ROSTER_ENDPOINT_TEMPLATE,
    CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
)
_SEASON_SUMMARIES_ENDPOINTS: tuple[str, ...] = (
    SKATER_SUMMARY_ENDPOINT_TEMPLATE,
    GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
    TEAM_SUMMARY_ENDPOINT_TEMPLATE,
)

#: CLI-exposed phase identifiers + the implicit "all" alias. Lives
#: here rather than in :mod:`cli` so non-CLI callers (M10's Dagster
#: assets) can import the same vocabulary without pulling argparse.
PHASE_TEAM_SEASON: str = "team-season"
PHASE_SEASON_SUMMARIES: str = "season-summaries"
PHASE_GAMES: str = "games"
PHASE_ALL: str = "all"

#: Phase order when ``--loader=all``. Cheap-fail-fast: team-season is
#: ~3 min wall, season-summaries is ~30 sec, games is ~5-6 hrs.
ALL_PHASE_ORDER: tuple[str, ...] = (
    PHASE_TEAM_SEASON,
    PHASE_SEASON_SUMMARIES,
    PHASE_GAMES,
)

#: All recognized values for the ``loader`` argument, including the
#: "all" alias. Used by the CLI's ``choices=`` plus by callers that
#: want to validate a string against the supported set without a
#: try/except.
SUPPORTED_LOADERS: tuple[str, ...] = (
    PHASE_GAMES,
    PHASE_SEASON_SUMMARIES,
    PHASE_TEAM_SEASON,
    PHASE_ALL,
)


@dataclass(frozen=True)
class BackfillCollaborators:
    """Bundle of injected loaders + manifest the orchestrator needs.

    A single struct rather than four positional arguments because every
    phase needs the manifest, the orchestrator wires all four together
    by construction, and the test seam (one factory in :mod:`cli`) is
    cleaner with one return value.

    No ``RateLimitedClient`` lives here directly — clients are owned by
    the loaders that hold them. The CLI factory shares one client
    across all four loaders so the rate-limit budget is process-wide
    (D6); the orchestrator never sees the client itself.
    """

    daily_loader: DailyLoader
    season_summaries_loader: SeasonSummariesLoader
    team_season_loader: TeamSeasonLoader
    manifest: ManifestStore


@dataclass(frozen=True)
class PhaseResult:
    """Summary of one phase's work.

    "Scope unit" is the loader-specific unit of idempotent dedupe:
    one ``(season, team)`` pair for ``team-season``, one season for
    ``season-summaries``, one game for ``games``. ``attempted`` counts
    every scope unit the phase visited (skipped or loaded). For the
    games phase, the count comes from the daily loader's eligible-game
    counts aggregated across days — empty schedule days don't
    contribute.
    """

    phase: str
    scope_units_attempted: int
    scope_units_skipped: int
    scope_units_loaded: int
    manifest_entries_appended: int


@dataclass(frozen=True)
class BackfillResult:
    """Summary of one :func:`run_backfill` invocation.

    ``aborted`` flips when a cost-check trip in ``fail`` mode short-
    circuits the phase loop. The completed phases up to the abort still
    appear in ``phase_results``, in the order they ran, so a follow-up
    run can resume from where the abort left off.
    """

    run_id: str
    seasons: list[str]
    loader: str
    cost_check_mode: str
    ingest_date: date
    phase_results: list[PhaseResult] = field(default_factory=list)
    aborted: bool = False
    aborted_reason: str | None = None


def run_backfill(
    collaborators: BackfillCollaborators,
    *,
    seasons: list[str],
    loader: str = PHASE_ALL,
    cost_check_mode: CostCheckMode = "fail",
    ingest_date: date | None = None,
    run_id: str | None = None,
) -> BackfillResult:
    """Run the requested backfill phase(s) across ``seasons``.

    Args:
        collaborators: Wired loaders + manifest. The CLI builds these
            from environment-driven settings; tests pass stubs that
            target ``LocalFilesystemStorage`` + ``httpx.MockTransport``.
        seasons: Already-normalized 8-digit season ids (e.g.
            ``["20152016", "20162017", ...]``). The CLI runs the
            ``YYYY-YY`` / ``YYYYYYYY`` normalization via
            :func:`parse_season_range` before calling here, so the
            orchestrator only sees the canonical form. Defensive
            re-normalization happens inside each phase anyway, so a
            non-canonical input is handled but discouraged.
        loader: One of :data:`SUPPORTED_LOADERS`. ``"all"`` runs the
            three phases in :data:`ALL_PHASE_ORDER`. Per-phase values
            run only that one phase.
        cost_check_mode: ``"fail"`` (default), ``"warn"``, or ``"off"``.
            Controls behavior when the end-of-phase projection exceeds
            the active threshold (see :mod:`puckbunny.ingestion.cost_check`).
        ingest_date: Bronze partition key override. Defaults to today's
            UTC date — backfills run in one logical "ingest day" so all
            partitions write to the same date directory. Override only
            if you need to pin to a specific historical partition for
            replay testing.
        run_id: Optional override for the run id stamped on every
            manifest entry written by this backfill. When omitted, a
            fresh hex id is minted via :func:`new_run_id`. Tests pass
            a fixed value to keep manifest assertions deterministic.

    Returns:
        :class:`BackfillResult` with one :class:`PhaseResult` per
        phase that ran. ``aborted`` reflects whether a cost-check
        trip cut the run short.

    Raises:
        ValueError: ``loader`` is not in :data:`SUPPORTED_LOADERS`.
        Any exception raised by a loader's ``load_one`` /
            ``load_date`` propagates — the orchestrator does not catch
            generic exceptions. The completed manifest writes up to the
            failure are durable, so re-invocation resumes correctly.
    """
    if loader not in SUPPORTED_LOADERS:
        raise ValueError(f"unknown loader {loader!r}; expected one of {SUPPORTED_LOADERS}")

    ingest_date = ingest_date or datetime.now(UTC).date()
    run_id = run_id or new_run_id()
    log = structlog.get_logger(__name__).bind(
        run_id=run_id,
        seasons=seasons,
        loader=loader,
        cost_check_mode=cost_check_mode,
        ingest_date=ingest_date.isoformat(),
    )
    log.info("backfill_start")

    phases: tuple[str, ...] = ALL_PHASE_ORDER if loader == PHASE_ALL else (loader,)

    phase_results: list[PhaseResult] = []
    aborted = False
    aborted_reason: str | None = None

    for phase in phases:
        result = _run_one_phase(
            phase=phase,
            collaborators=collaborators,
            seasons=seasons,
            ingest_date=ingest_date,
            run_id=run_id,
        )
        phase_results.append(result)

        # End-of-phase cost-check. Per Q2: no separate end-of-overall
        # pass — the last phase's check IS the end-of-overall, so a
        # single-phase invocation gets one check and a 3-phase
        # invocation gets three.
        projection = compute_projection(collaborators.manifest, run_id=run_id)
        try:
            evaluate_cost_check(projection, cost_check_mode)
        except CostCheckTripped as exc:
            aborted = True
            aborted_reason = str(exc)
            log.error("backfill_aborted_cost_check", phase=phase)
            break

    log.info("backfill_complete", aborted=aborted, phases_run=len(phase_results))
    return BackfillResult(
        run_id=run_id,
        seasons=seasons,
        loader=loader,
        cost_check_mode=cost_check_mode,
        ingest_date=ingest_date,
        phase_results=phase_results,
        aborted=aborted,
        aborted_reason=aborted_reason,
    )


def _run_one_phase(
    *,
    phase: str,
    collaborators: BackfillCollaborators,
    seasons: list[str],
    ingest_date: date,
    run_id: str,
) -> PhaseResult:
    """Dispatch one phase by name. Centralized so :func:`run_backfill`
    stays a control-flow shell with the per-phase work isolated."""
    if phase == PHASE_TEAM_SEASON:
        return backfill_team_season(
            collaborators,
            seasons=seasons,
            ingest_date=ingest_date,
            run_id=run_id,
        )
    if phase == PHASE_SEASON_SUMMARIES:
        return backfill_season_summaries(
            collaborators,
            seasons=seasons,
            ingest_date=ingest_date,
            run_id=run_id,
        )
    if phase == PHASE_GAMES:
        return backfill_games(
            collaborators,
            seasons=seasons,
            ingest_date=ingest_date,
            run_id=run_id,
        )
    raise ValueError(f"unknown phase {phase!r}")


def backfill_team_season(
    collaborators: BackfillCollaborators,
    *,
    seasons: list[str],
    ingest_date: date,
    run_id: str,
) -> PhaseResult:
    """Iterate ``(season, team)`` pairs, gating per the D11 table.

    For each pair:

    * If both ``roster`` and ``club-schedule-season`` manifest entries
      already exist for ``f"{season}|{team}"``, skip.
    * Otherwise call :meth:`TeamSeasonLoader.load_one` (re-fetches
      both endpoints) and append manifest entries for the non-``None``
      slots only — a 404 leaves a slot ``None`` and that endpoint gets
      no manifest entry, so subsequent runs re-attempt it (bounded by
      ``team_abbrevs``).

    Order: outer loop over ``seasons`` (early seasons first so a
    backfill failure leaves a contiguous prefix done); inner loop over
    ``sorted(team_abbrevs(season))`` for a deterministic, season-aware
    team set (VGK/SEA/UTA franchise events are encoded in
    :func:`team_abbrevs`).
    """
    log = structlog.get_logger(__name__).bind(
        phase=PHASE_TEAM_SEASON,
        run_id=run_id,
        seasons_count=len(seasons),
    )
    log.info("phase_start")

    attempted = 0
    skipped = 0
    loaded = 0
    appended_total = 0

    for season in seasons:
        season_norm = format_season_id(season)
        for team in sorted(team_abbrevs(season_norm)):
            attempted += 1
            scope_key = f"{season_norm}|{team}"

            if all(collaborators.manifest.has(ep, scope_key) for ep in _TEAM_SEASON_ENDPOINTS):
                skipped += 1
                log.debug(
                    "team_season_scope_skipped",
                    season=season_norm,
                    team=team,
                )
                continue

            result = collaborators.team_season_loader.load_one(
                season_norm, team, ingest_date=ingest_date
            )

            entries: list[ManifestEntry] = []
            if result.roster is not None:
                entries.append(
                    build_entry(
                        run_id=run_id,
                        endpoint=ROSTER_ENDPOINT_TEMPLATE,
                        scope_key=scope_key,
                        rows=result.roster.rows,
                        bytes_written=result.roster.bytes,
                    )
                )
            if result.club_schedule_season is not None:
                entries.append(
                    build_entry(
                        run_id=run_id,
                        endpoint=CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
                        scope_key=scope_key,
                        rows=result.club_schedule_season.rows,
                        bytes_written=result.club_schedule_season.bytes,
                    )
                )

            if entries:
                appended_total += collaborators.manifest.append_many(entries)
            loaded += 1

    log.info(
        "phase_complete",
        attempted=attempted,
        skipped=skipped,
        loaded=loaded,
        appended=appended_total,
    )
    return PhaseResult(
        phase=PHASE_TEAM_SEASON,
        scope_units_attempted=attempted,
        scope_units_skipped=skipped,
        scope_units_loaded=loaded,
        manifest_entries_appended=appended_total,
    )


def backfill_season_summaries(
    collaborators: BackfillCollaborators,
    *,
    seasons: list[str],
    ingest_date: date,
    run_id: str,
) -> PhaseResult:
    """Iterate seasons, gating per the D11 table.

    For each season:

    * If all three (skater / goalie / team) summary manifest entries
      already exist for the season, skip.
    * Otherwise call :meth:`SeasonSummariesLoader.load_one` (re-fetches
      all three) and append all three manifest entries — there's no
      404 case on this surface (the loader raises on any HTTP error),
      so the result's three slots are always non-``None``.
    """
    log = structlog.get_logger(__name__).bind(
        phase=PHASE_SEASON_SUMMARIES,
        run_id=run_id,
        seasons_count=len(seasons),
    )
    log.info("phase_start")

    attempted = 0
    skipped = 0
    loaded = 0
    appended_total = 0

    for season in seasons:
        scope_key = format_season_id(season)
        attempted += 1

        if all(collaborators.manifest.has(ep, scope_key) for ep in _SEASON_SUMMARIES_ENDPOINTS):
            skipped += 1
            log.debug("season_summaries_scope_skipped", season=scope_key)
            continue

        result = collaborators.season_summaries_loader.load_one(scope_key, ingest_date=ingest_date)

        entries: list[ManifestEntry] = [
            build_entry(
                run_id=run_id,
                endpoint=SKATER_SUMMARY_ENDPOINT_TEMPLATE,
                scope_key=scope_key,
                rows=result.skater_summary.rows,
                bytes_written=result.skater_summary.bytes,
            ),
            build_entry(
                run_id=run_id,
                endpoint=GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
                scope_key=scope_key,
                rows=result.goalie_summary.rows,
                bytes_written=result.goalie_summary.bytes,
            ),
            build_entry(
                run_id=run_id,
                endpoint=TEAM_SUMMARY_ENDPOINT_TEMPLATE,
                scope_key=scope_key,
                rows=result.team_summary.rows,
                bytes_written=result.team_summary.bytes,
            ),
        ]
        appended_total += collaborators.manifest.append_many(entries)
        loaded += 1

    log.info(
        "phase_complete",
        attempted=attempted,
        skipped=skipped,
        loaded=loaded,
        appended=appended_total,
    )
    return PhaseResult(
        phase=PHASE_SEASON_SUMMARIES,
        scope_units_attempted=attempted,
        scope_units_skipped=skipped,
        scope_units_loaded=loaded,
        manifest_entries_appended=appended_total,
    )


def backfill_games(
    collaborators: BackfillCollaborators,
    *,
    seasons: list[str],
    ingest_date: date,
    run_id: str,
) -> PhaseResult:
    """Iterate dates in each season's window, delegating to :class:`DailyLoader`.

    Per D8: pure schedule day-walks. For each calendar date in
    :func:`dates_in_season` (Sept 1 → June 30 inclusive):

    * Call :meth:`DailyLoader.load_date` with the shared ``run_id``.
    * Empty days are no-ops inside ``DailyLoader`` (zero eligible games,
      zero outcomes); we still pay one schedule fetch per date.

    The orchestrator does **no** game-level gating — that's
    ``DailyLoader``'s job, and pulling it up here would duplicate the
    PR-E logic and split daily-vs-backfill behavior on the same
    primitive. The phase result aggregates the per-day eligibility /
    skip / load counts.

    Manifest entries are written by ``DailyLoader`` itself (3 per loaded
    game), so the phase's ``manifest_entries_appended`` is computed as
    ``games_loaded * 3`` rather than tallied at the orchestrator level.
    """
    log = structlog.get_logger(__name__).bind(
        phase=PHASE_GAMES,
        run_id=run_id,
        seasons_count=len(seasons),
    )
    log.info("phase_start")

    attempted = 0
    skipped = 0
    loaded = 0
    dates_walked = 0

    for season in seasons:
        season_norm = format_season_id(season)
        for d in dates_in_season(season_norm):
            dates_walked += 1
            daily_result = collaborators.daily_loader.load_date(
                d,
                ingest_date=ingest_date,
                run_id=run_id,
            )
            attempted += daily_result.games_eligible
            skipped += daily_result.games_skipped
            loaded += daily_result.games_loaded

    log.info(
        "phase_complete",
        attempted=attempted,
        skipped=skipped,
        loaded=loaded,
        dates_walked=dates_walked,
    )
    return PhaseResult(
        phase=PHASE_GAMES,
        scope_units_attempted=attempted,
        scope_units_skipped=skipped,
        scope_units_loaded=loaded,
        # 3 manifest entries per game (landing + boxscore + PxP) per
        # PR-E. Computed rather than tallied because DailyLoader owns
        # the manifest write and doesn't expose per-call counts.
        manifest_entries_appended=loaded * 3,
    )


__all__ = [
    "ALL_PHASE_ORDER",
    "PHASE_ALL",
    "PHASE_GAMES",
    "PHASE_SEASON_SUMMARIES",
    "PHASE_TEAM_SEASON",
    "SUPPORTED_LOADERS",
    "BackfillCollaborators",
    "BackfillResult",
    "PhaseResult",
    "backfill_games",
    "backfill_season_summaries",
    "backfill_team_season",
    "run_backfill",
]
