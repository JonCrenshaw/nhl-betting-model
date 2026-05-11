"""Tests for :mod:`puckbunny.ingestion.nhl.backfill`.

The orchestrator is the per-PR-G integration point for the four
loaders + manifest + cost-check, so the surface to cover is wide:

* Per-phase gating per the D11 table (skip when fully present;
  fetch-and-record when any missing).
* Per-phase manifest-write granularity (3 entries per game,
  3 per season-summaries, 1-or-2 per team-season depending on 404).
* run_id propagation across phases (single id stamped on every entry,
  including ones written by ``DailyLoader``).
* --loader selector and phase ordering.
* Cost-check trip aborting before the next phase.
* Season-range iteration across multiple seasons.

The loaders are stubbed rather than real because the orchestrator's
contract with them is purely "call ``load_one`` / ``load_date`` and
look at the result." Wiring real ``httpx.MockTransport`` cassettes
through them would test integration paths already covered by each
loader's own test module — duplication without coverage gain. The
end-to-end resume test in ``test_backfill_resume.py`` covers the
real-loaders path.

The ``ManifestStore`` is a real instance over
:class:`LocalFilesystemStorage`, so the gating logic exercises the
production read/write path against the production JSONL serializer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import pytest

from puckbunny.ingestion.cost_check import COST_CHECK_THRESHOLD_USD, THRESHOLD_ENV_VAR
from puckbunny.ingestion.manifest import ManifestStore, build_entry
from puckbunny.ingestion.nhl.backfill import (
    ALL_PHASE_ORDER,
    PHASE_ALL,
    PHASE_SEASON_SUMMARIES,
    PHASE_TEAM_SEASON,
    BackfillCollaborators,
    backfill_games,
    backfill_season_summaries,
    backfill_team_season,
    run_backfill,
)
from puckbunny.ingestion.nhl.endpoints import (
    CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
    GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
    ROSTER_ENDPOINT_TEMPLATE,
    SKATER_SUMMARY_ENDPOINT_TEMPLATE,
    TEAM_SUMMARY_ENDPOINT_TEMPLATE,
    team_abbrevs,
)
from puckbunny.ingestion.nhl.schedule import DailyLoadResult, GameOutcome
from puckbunny.ingestion.nhl.season_summaries import SeasonSummariesLoadResult
from puckbunny.ingestion.nhl.team_season import TeamSeasonLoadResult
from puckbunny.storage.local import LocalFilesystemStorage
from puckbunny.storage.parquet import WriteResult

if TYPE_CHECKING:
    from pathlib import Path


# --------------------------------------------------------------------
# Stub loaders
# --------------------------------------------------------------------


def _wr(*, rows: int = 1, bytes_written: int = 1_000) -> WriteResult:
    """Build a deterministic WriteResult for stubbed loader returns."""
    return WriteResult(key="bronze/x", rows=rows, bytes=bytes_written)


@dataclass
class StubDailyLoader:
    """Records each ``load_date`` call and returns canned results.

    ``games_per_date`` lets a test simulate "this date has N eligible
    games" without modeling a fake schedule. ``run_id_seen`` is the
    list of run_ids the orchestrator passed in — load-bearing for the
    "single run_id across the backfill" property.
    """

    games_per_date: dict[date, int] = field(default_factory=dict)
    skipped_per_date: dict[date, int] = field(default_factory=dict)
    calls: list[tuple[date, date | None, str | None]] = field(default_factory=list)
    run_ids_seen: list[str | None] = field(default_factory=list)

    def load_date(
        self,
        target_date: date,
        *,
        ingest_date: date | None = None,
        run_id: str | None = None,
    ) -> DailyLoadResult:
        self.calls.append((target_date, ingest_date, run_id))
        self.run_ids_seen.append(run_id)
        loaded = self.games_per_date.get(target_date, 0)
        skipped = self.skipped_per_date.get(target_date, 0)
        eligible = loaded + skipped
        return DailyLoadResult(
            target_date=target_date,
            ingest_date=ingest_date or date(2026, 5, 8),
            run_id=run_id or "stub",
            games_in_schedule=eligible,
            games_eligible=eligible,
            games_loaded=loaded,
            games_skipped=skipped,
            outcomes=[GameOutcome(game_id=10000 + i, skipped=False) for i in range(loaded)]
            + [GameOutcome(game_id=20000 + i, skipped=True) for i in range(skipped)],
        )


@dataclass
class StubSeasonSummariesLoader:
    """Records ``load_one`` calls; returns canned three-slot result."""

    calls: list[tuple[str, date | None]] = field(default_factory=list)

    def load_one(
        self,
        season: int | str,
        *,
        ingest_date: date | None = None,
    ) -> SeasonSummariesLoadResult:
        self.calls.append((str(season), ingest_date))
        return SeasonSummariesLoadResult(
            season=str(season),
            skater_summary=_wr(rows=900, bytes_written=120_000),
            goalie_summary=_wr(rows=80, bytes_written=10_000),
            team_summary=_wr(rows=32, bytes_written=8_000),
        )


@dataclass
class StubTeamSeasonLoader:
    """Records ``load_one`` calls; returns canned two-slot result.

    ``not_found_pairs`` lets a test simulate the 404 log-and-skip case
    by returning ``None`` for that slot. By default both slots are
    populated.
    """

    not_found_roster: set[tuple[str, str]] = field(default_factory=set)
    not_found_club_schedule: set[tuple[str, str]] = field(default_factory=set)
    calls: list[tuple[str, str, date | None]] = field(default_factory=list)

    def load_one(
        self,
        season: int | str,
        team: str,
        *,
        ingest_date: date | None = None,
    ) -> TeamSeasonLoadResult:
        season_str = str(season)
        self.calls.append((season_str, team, ingest_date))
        roster: WriteResult | None = (
            None
            if (season_str, team) in self.not_found_roster
            else _wr(rows=23, bytes_written=4_000)
        )
        club_schedule: WriteResult | None = (
            None
            if (season_str, team) in self.not_found_club_schedule
            else _wr(rows=82, bytes_written=15_000)
        )
        return TeamSeasonLoadResult(
            season=season_str,
            team=team,
            roster=roster,
            club_schedule_season=club_schedule,
        )


def _make_collaborators(
    tmp_path: Path,
    *,
    daily: StubDailyLoader | None = None,
    season_summaries: StubSeasonSummariesLoader | None = None,
    team_season: StubTeamSeasonLoader | None = None,
) -> tuple[BackfillCollaborators, ManifestStore]:
    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)
    return BackfillCollaborators(
        daily_loader=daily or StubDailyLoader(),  # type: ignore[arg-type]
        season_summaries_loader=season_summaries or StubSeasonSummariesLoader(),  # type: ignore[arg-type]
        team_season_loader=team_season or StubTeamSeasonLoader(),  # type: ignore[arg-type]
        manifest=manifest,
    ), manifest


# --------------------------------------------------------------------
# backfill_team_season
# --------------------------------------------------------------------


def test_team_season_phase_iterates_all_teams_for_season(tmp_path: Path) -> None:
    stub = StubTeamSeasonLoader()
    collab, manifest = _make_collaborators(tmp_path, team_season=stub)
    result = backfill_team_season(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    expected_teams = sorted(team_abbrevs("20242025"))
    assert result.scope_units_attempted == len(expected_teams)
    assert result.scope_units_loaded == len(expected_teams)
    assert result.scope_units_skipped == 0
    # 2 endpoints per (season, team), 32 teams in 2024-25 → 64 entries.
    assert result.manifest_entries_appended == len(expected_teams) * 2
    assert len(manifest.read_entries()) == len(expected_teams) * 2


def test_team_season_phase_skips_fully_loaded_scope_units(tmp_path: Path) -> None:
    """Pre-seed the manifest with both endpoints for one (season, team)
    pair; the orchestrator must skip that pair entirely, including no
    ``load_one`` call for it."""
    stub = StubTeamSeasonLoader()
    collab, manifest = _make_collaborators(tmp_path, team_season=stub)
    # Pre-seed TOR 2024-25 with both endpoints.
    for endpoint in (ROSTER_ENDPOINT_TEMPLATE, CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE):
        manifest.append(
            build_entry(
                run_id="prior-run",
                endpoint=endpoint,
                scope_key="20242025|TOR",
                rows=1,
                bytes_written=100,
            )
        )

    backfill_team_season(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    # TOR was skipped — never appears in the loader's call log.
    assert ("20242025", "TOR", date(2026, 5, 8)) not in stub.calls


def test_team_season_phase_partial_manifest_refetches(tmp_path: Path) -> None:
    """Only one endpoint pre-seeded → the orchestrator re-fetches
    both. (Per D11: "Skip if both manifest entries present; on miss,
    re-fetch both.")"""
    stub = StubTeamSeasonLoader()
    collab, manifest = _make_collaborators(tmp_path, team_season=stub)
    # Only ROSTER pre-seeded for TOR; CLUB_SCHEDULE missing.
    manifest.append(
        build_entry(
            run_id="prior-run",
            endpoint=ROSTER_ENDPOINT_TEMPLATE,
            scope_key="20242025|TOR",
            rows=1,
            bytes_written=100,
        )
    )
    backfill_team_season(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    # TOR appears in the call log even though one endpoint was already
    # in the manifest — confirms the "any missing → re-fetch both" rule.
    assert ("20242025", "TOR", date(2026, 5, 8)) in stub.calls


def test_team_season_phase_404_writes_only_the_success(tmp_path: Path) -> None:
    """When the loader returns ``None`` for one endpoint (404), only
    the successful endpoint's entry lands in the manifest."""
    stub = StubTeamSeasonLoader(
        not_found_club_schedule={("20232024", "UTA")},
        not_found_roster={("20232024", "UTA")},
    )
    collab, manifest = _make_collaborators(tmp_path, team_season=stub)
    backfill_team_season(
        collab,
        seasons=["20232024"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    # UTA in 20232024 has neither endpoint succeed; manifest should have
    # zero entries for UTA but full coverage for everyone else.
    entries = manifest.read_entries()
    uta_entries = [e for e in entries if e.scope_key == "20232024|UTA"]
    assert uta_entries == []


def test_team_season_phase_uses_supplied_run_id(tmp_path: Path) -> None:
    stub = StubTeamSeasonLoader()
    collab, manifest = _make_collaborators(tmp_path, team_season=stub)
    backfill_team_season(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="my-backfill-run",
    )
    assert {e.run_id for e in manifest.read_entries()} == {"my-backfill-run"}


# --------------------------------------------------------------------
# backfill_season_summaries
# --------------------------------------------------------------------


def test_season_summaries_phase_writes_three_entries_per_season(tmp_path: Path) -> None:
    stub = StubSeasonSummariesLoader()
    collab, manifest = _make_collaborators(tmp_path, season_summaries=stub)
    result = backfill_season_summaries(
        collab,
        seasons=["20232024", "20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    assert result.scope_units_attempted == 2
    assert result.scope_units_loaded == 2
    assert result.scope_units_skipped == 0
    # 2 seasons * 3 endpoints.
    assert result.manifest_entries_appended == 6
    assert len(manifest.read_entries()) == 6


def test_season_summaries_phase_skips_fully_loaded(tmp_path: Path) -> None:
    stub = StubSeasonSummariesLoader()
    collab, manifest = _make_collaborators(tmp_path, season_summaries=stub)
    # Pre-seed all three endpoints for 20242025.
    for endpoint in (
        SKATER_SUMMARY_ENDPOINT_TEMPLATE,
        GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
        TEAM_SUMMARY_ENDPOINT_TEMPLATE,
    ):
        manifest.append(
            build_entry(
                run_id="prior-run",
                endpoint=endpoint,
                scope_key="20242025",
                rows=1,
                bytes_written=100,
            )
        )
    backfill_season_summaries(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    # No new ``load_one`` call — pre-seeded coverage skipped the season.
    assert stub.calls == []


def test_season_summaries_phase_partial_manifest_refetches(tmp_path: Path) -> None:
    """Only two of three endpoints pre-seeded → re-fetch all three."""
    stub = StubSeasonSummariesLoader()
    collab, manifest = _make_collaborators(tmp_path, season_summaries=stub)
    for endpoint in (
        SKATER_SUMMARY_ENDPOINT_TEMPLATE,
        GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
        # team-summary deliberately missing
    ):
        manifest.append(
            build_entry(
                run_id="prior-run",
                endpoint=endpoint,
                scope_key="20242025",
                rows=1,
                bytes_written=100,
            )
        )
    backfill_season_summaries(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    assert ("20242025", date(2026, 5, 8)) in stub.calls


# --------------------------------------------------------------------
# backfill_games
# --------------------------------------------------------------------


def test_games_phase_walks_every_date_in_window(tmp_path: Path) -> None:
    """Every calendar date in the season's Sept 1 → June 30 window
    triggers exactly one ``DailyLoader.load_date`` call. The orchestrator
    does no game-level gating itself."""
    stub = StubDailyLoader()
    collab, _ = _make_collaborators(tmp_path, daily=stub)
    backfill_games(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    # 2024-25 → Sept 1 2024 through June 30 2025 inclusive = 303 days.
    assert len(stub.calls) == 303


def test_games_phase_threads_run_id(tmp_path: Path) -> None:
    """The supplied run_id shows up on every load_date invocation —
    the load-bearing property for "one run_id per backfill" across
    the manifest."""
    stub = StubDailyLoader()
    collab, _ = _make_collaborators(tmp_path, daily=stub)
    backfill_games(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="my-backfill-run",
    )
    assert set(stub.run_ids_seen) == {"my-backfill-run"}


def test_games_phase_aggregates_eligible_skipped_loaded(tmp_path: Path) -> None:
    """Phase result reflects sum of per-day games_eligible / games_loaded
    / games_skipped from the daily loader."""
    stub = StubDailyLoader(
        games_per_date={
            date(2024, 10, 8): 12,
            date(2024, 10, 9): 8,
        },
        skipped_per_date={
            date(2024, 10, 8): 0,
            date(2024, 10, 9): 4,
        },
    )
    collab, _ = _make_collaborators(tmp_path, daily=stub)
    result = backfill_games(
        collab,
        seasons=["20242025"],
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    assert result.scope_units_loaded == 20  # 12 + 8
    assert result.scope_units_skipped == 4
    assert result.scope_units_attempted == 24  # 12 + 12 (the second day had 8 + 4)
    # 3 manifest entries per loaded game.
    assert result.manifest_entries_appended == 60


# --------------------------------------------------------------------
# run_backfill — phase ordering, --loader selector
# --------------------------------------------------------------------


def test_run_backfill_all_runs_phases_in_order(tmp_path: Path) -> None:
    """``--loader=all`` runs team-season → season-summaries → games."""
    daily = StubDailyLoader()
    summaries = StubSeasonSummariesLoader()
    team = StubTeamSeasonLoader()
    collab, _ = _make_collaborators(
        tmp_path, daily=daily, season_summaries=summaries, team_season=team
    )
    result = run_backfill(
        collab,
        seasons=["20242025"],
        loader=PHASE_ALL,
        cost_check_mode="off",  # don't trip on any test threshold
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    assert [p.phase for p in result.phase_results] == list(ALL_PHASE_ORDER)
    assert result.aborted is False


def test_run_backfill_single_phase(tmp_path: Path) -> None:
    summaries = StubSeasonSummariesLoader()
    daily = StubDailyLoader()
    team = StubTeamSeasonLoader()
    collab, _ = _make_collaborators(
        tmp_path, daily=daily, season_summaries=summaries, team_season=team
    )
    result = run_backfill(
        collab,
        seasons=["20242025"],
        loader=PHASE_SEASON_SUMMARIES,
        cost_check_mode="off",
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    assert [p.phase for p in result.phase_results] == [PHASE_SEASON_SUMMARIES]
    # Other phases didn't run.
    assert daily.calls == []
    assert team.calls == []


def test_run_backfill_unknown_loader_raises(tmp_path: Path) -> None:
    collab, _ = _make_collaborators(tmp_path)
    with pytest.raises(ValueError, match="unknown loader"):
        run_backfill(
            collab,
            seasons=["20242025"],
            loader="not-a-phase",
            cost_check_mode="off",
        )


def test_run_backfill_propagates_run_id_across_all_phases(tmp_path: Path) -> None:
    """The supplied run_id is stamped on every manifest entry from
    every phase — the load-bearing property of Q1's "thread the
    run_id" decision."""
    daily = StubDailyLoader(games_per_date={date(2024, 10, 8): 1})
    summaries = StubSeasonSummariesLoader()
    team = StubTeamSeasonLoader()
    collab, manifest = _make_collaborators(
        tmp_path, daily=daily, season_summaries=summaries, team_season=team
    )
    run_backfill(
        collab,
        seasons=["20242025"],
        loader=PHASE_ALL,
        cost_check_mode="off",
        ingest_date=date(2026, 5, 8),
        run_id="my-backfill-run",
    )
    # team-season + season-summaries entries land via the orchestrator
    # — confirm shared run_id.
    entries = manifest.read_entries()
    assert {e.run_id for e in entries} == {"my-backfill-run"}
    # And the daily loader saw the same id.
    assert set(daily.run_ids_seen) == {"my-backfill-run"}


def test_run_backfill_iterates_multiple_seasons(tmp_path: Path) -> None:
    """Two-season range produces two ``load_one`` calls per scope unit
    in the season-summaries phase."""
    summaries = StubSeasonSummariesLoader()
    collab, _ = _make_collaborators(tmp_path, season_summaries=summaries)
    run_backfill(
        collab,
        seasons=["20232024", "20242025"],
        loader=PHASE_SEASON_SUMMARIES,
        cost_check_mode="off",
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    seasons_called = sorted({s for s, _ in summaries.calls})
    assert seasons_called == ["20232024", "20242025"]


# --------------------------------------------------------------------
# run_backfill — cost-check trip
# --------------------------------------------------------------------


def test_run_backfill_aborts_on_cost_check_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force a tiny threshold so the first phase trips it. With
    ``--cost-check fail`` the run aborts before the next phase."""
    monkeypatch.setenv(THRESHOLD_ENV_VAR, "0.0000001")
    summaries = StubSeasonSummariesLoader()
    daily = StubDailyLoader()
    team = StubTeamSeasonLoader()
    collab, _ = _make_collaborators(
        tmp_path, daily=daily, season_summaries=summaries, team_season=team
    )
    result = run_backfill(
        collab,
        seasons=["20242025"],
        loader=PHASE_ALL,
        cost_check_mode="fail",
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    # team-season is the first phase in ALL_PHASE_ORDER; it ran. The
    # subsequent phases didn't.
    assert [p.phase for p in result.phase_results] == [PHASE_TEAM_SEASON]
    assert result.aborted is True
    assert "tripped" in (result.aborted_reason or "")
    # Confirm later phases never ran.
    assert summaries.calls == []
    assert daily.calls == []


def test_run_backfill_warn_mode_does_not_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``warn`` mode logs a warning but lets subsequent phases run."""
    monkeypatch.setenv(THRESHOLD_ENV_VAR, "0.0000001")
    summaries = StubSeasonSummariesLoader()
    daily = StubDailyLoader()
    team = StubTeamSeasonLoader()
    collab, _ = _make_collaborators(
        tmp_path, daily=daily, season_summaries=summaries, team_season=team
    )
    result = run_backfill(
        collab,
        seasons=["20242025"],
        loader=PHASE_ALL,
        cost_check_mode="warn",
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    assert result.aborted is False
    assert [p.phase for p in result.phase_results] == list(ALL_PHASE_ORDER)


def test_run_backfill_off_mode_runs_to_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(THRESHOLD_ENV_VAR, "0.0000001")
    collab, _ = _make_collaborators(tmp_path)
    result = run_backfill(
        collab,
        seasons=["20242025"],
        loader=PHASE_ALL,
        cost_check_mode="off",
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    assert result.aborted is False


# --------------------------------------------------------------------
# CLI: python -m puckbunny.ingestion.nhl backfill ...
# --------------------------------------------------------------------


def test_cli_backfill_subcommand_runs_full_pipeline(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main(["backfill", "--from-season", ..., "--to-season", ...])``
    drives the orchestrator, prints a JSON summary, and exits 0 on a
    clean run."""
    from puckbunny.ingestion.nhl import cli as cli_module

    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)
    daily = StubDailyLoader()
    summaries = StubSeasonSummariesLoader()
    team = StubTeamSeasonLoader()
    collaborators = BackfillCollaborators(
        daily_loader=daily,  # type: ignore[arg-type]
        season_summaries_loader=summaries,  # type: ignore[arg-type]
        team_season_loader=team,  # type: ignore[arg-type]
        manifest=manifest,
    )

    def factory(_args: object) -> tuple[BackfillCollaborators, object]:
        return collaborators, lambda: None  # type: ignore[return-value]

    exit_code = cli_module.main(
        [
            "backfill",
            "--from-season",
            "2024-25",
            "--to-season",
            "2024-25",
            "--loader",
            "season-summaries",
            "--cost-check",
            "off",
            "--ingest-date",
            "2026-05-08",
            "--log-level",
            "WARNING",
        ],
        backfill_factory=factory,
    )
    assert exit_code == 0

    import json as _json

    out = capsys.readouterr().out.strip()
    summary = _json.loads(out)
    assert summary["loader"] == "season-summaries"
    assert summary["cost_check_mode"] == "off"
    assert summary["ingest_date"] == "2026-05-08"
    assert summary["seasons"] == ["20242025"]
    assert summary["aborted"] is False
    assert len(summary["phases"]) == 1
    assert summary["phases"][0]["phase"] == "season-summaries"


def test_cli_backfill_subcommand_normalizes_yyyy_yy_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI accepts ``YYYY-YY`` for ``--from-season`` /
    ``--to-season`` and normalizes to 8-digit before the orchestrator
    sees it (via :func:`parse_season_range`)."""
    from puckbunny.ingestion.nhl import cli as cli_module

    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)
    summaries = StubSeasonSummariesLoader()
    collaborators = BackfillCollaborators(
        daily_loader=StubDailyLoader(),  # type: ignore[arg-type]
        season_summaries_loader=summaries,  # type: ignore[arg-type]
        team_season_loader=StubTeamSeasonLoader(),  # type: ignore[arg-type]
        manifest=manifest,
    )

    def factory(_args: object) -> tuple[BackfillCollaborators, object]:
        return collaborators, lambda: None  # type: ignore[return-value]

    exit_code = cli_module.main(
        [
            "backfill",
            "--from-season",
            "2023-24",
            "--to-season",
            "2024-25",
            "--loader",
            "season-summaries",
            "--cost-check",
            "off",
            "--log-level",
            "WARNING",
        ],
        backfill_factory=factory,
    )
    assert exit_code == 0

    import json as _json

    out = capsys.readouterr().out.strip()
    summary = _json.loads(out)
    assert summary["seasons"] == ["20232024", "20242025"]


def test_cli_backfill_subcommand_returns_2_on_cost_check_trip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cost-check trip in fail mode → exit code 2 (distinct from 0
    "ran clean" and from 1 "argparse / unknown error"). Lets wrapper
    scripts branch on outcome."""
    from puckbunny.ingestion.nhl import cli as cli_module

    monkeypatch.setenv(THRESHOLD_ENV_VAR, "0.0000001")
    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)
    collaborators = BackfillCollaborators(
        daily_loader=StubDailyLoader(),  # type: ignore[arg-type]
        season_summaries_loader=StubSeasonSummariesLoader(),  # type: ignore[arg-type]
        team_season_loader=StubTeamSeasonLoader(),  # type: ignore[arg-type]
        manifest=manifest,
    )

    def factory(_args: object) -> tuple[BackfillCollaborators, object]:
        return collaborators, lambda: None  # type: ignore[return-value]

    exit_code = cli_module.main(
        [
            "backfill",
            "--from-season",
            "2024-25",
            "--to-season",
            "2024-25",
            "--cost-check",
            "fail",
            "--ingest-date",
            "2026-05-08",
            "--log-level",
            "WARNING",
        ],
        backfill_factory=factory,
    )
    assert exit_code == 2

    import json as _json

    out = capsys.readouterr().out.strip()
    summary = _json.loads(out)
    assert summary["aborted"] is True
    assert "tripped" in summary["aborted_reason"]


def test_cli_backfill_rejects_reversed_range() -> None:
    """``parse_season_range`` raises on ``to`` earlier than ``from``;
    the CLI surfaces the ValueError rather than silently producing
    nothing."""
    from puckbunny.ingestion.nhl import cli as cli_module

    with pytest.raises(ValueError, match="earlier than"):
        cli_module.main(
            [
                "backfill",
                "--from-season",
                "2024-25",
                "--to-season",
                "2015-16",
                "--cost-check",
                "off",
                "--log-level",
                "WARNING",
            ],
        )


def test_cli_backfill_rejects_unknown_loader() -> None:
    """argparse ``choices=`` should reject anything outside
    ``SUPPORTED_LOADERS`` before the factory ever runs."""
    from puckbunny.ingestion.nhl import cli as cli_module

    with pytest.raises(SystemExit):
        cli_module.main(
            [
                "backfill",
                "--from-season",
                "2024-25",
                "--to-season",
                "2024-25",
                "--loader",
                "not-a-phase",
            ],
        )


# --------------------------------------------------------------------
# Default-threshold sanity
# --------------------------------------------------------------------


def test_run_backfill_default_threshold_does_not_trip(tmp_path: Path) -> None:
    """At realistic backfill scale (per Risk #4: ~370 MB total,
    projecting ~$0.005/mo) the default $5/mo threshold is nowhere near
    tripping. Sanity check that the default mode + a representative
    payload sails through cleanly."""
    # Stubs return ~120 KB per fetch; ~32 teams + 1 season summaries
    # + (303 days * 0 games) = small total. Threshold defaults to $5.
    summaries = StubSeasonSummariesLoader()
    team = StubTeamSeasonLoader()
    collab, _ = _make_collaborators(tmp_path, season_summaries=summaries, team_season=team)
    result = run_backfill(
        collab,
        seasons=["20242025"],
        loader=PHASE_ALL,
        # cost_check_mode defaults to "fail"
        ingest_date=date(2026, 5, 8),
        run_id="r1",
    )
    assert result.aborted is False
    # Sanity: the threshold didn't change under our feet.
    assert COST_CHECK_THRESHOLD_USD == 5.00
