"""Live-API smoke tests for the backfill orchestrator.

Marked ``@pytest.mark.integration`` so they're excluded from default
CI per the M2 plan ("Risk #3: CI flake from integration tests"). Run
locally with ``uv run pytest -m integration tests/ingestion/test_smoke_integration.py``
to exercise the orchestrator against the real NHL API.

Scope is narrow: one season, ``--loader=season-summaries`` only. The
season-summaries surface is the cheapest of the three (3 GETs total),
honors our rate-limit budget, and exercises the orchestrator's
gating + manifest write end-to-end against a real (non-mocked) HTTP
transport.

Bronze is written under ``tmp_path`` via ``LocalFilesystemStorage``,
so this test never touches R2 — credentials aren't required and the
test leaves no cloud-side trace. The actual R2-as-bronze code path is
covered by ``tests/storage/test_r2.py``'s integration markers.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from puckbunny.http.client import RateLimitedClient
from puckbunny.ingestion.manifest import ManifestStore
from puckbunny.ingestion.nhl.backfill import (
    PHASE_SEASON_SUMMARIES,
    BackfillCollaborators,
    run_backfill,
)
from puckbunny.ingestion.nhl.endpoints import (
    GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
    SKATER_SUMMARY_ENDPOINT_TEMPLATE,
    TEAM_SUMMARY_ENDPOINT_TEMPLATE,
)
from puckbunny.ingestion.nhl.games import GameLoader
from puckbunny.ingestion.nhl.play_by_play import PlayByPlayLoader
from puckbunny.ingestion.nhl.schedule import DailyLoader, ScheduleLoader
from puckbunny.ingestion.nhl.season_summaries import SeasonSummariesLoader
from puckbunny.ingestion.nhl.team_season import TeamSeasonLoader
from puckbunny.storage.local import LocalFilesystemStorage

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
def test_season_summaries_backfill_smoke_against_live_api(tmp_path: Path) -> None:
    """End-to-end: ``run_backfill --loader=season-summaries`` for the
    most recently completed regular season (2023-24) against the
    live NHL API.

    2023-24 is chosen rather than the in-progress season so the
    response payload is finalized — flakier "season is still running"
    edge cases (incomplete totals, partial week tails) don't apply.
    """
    season = "20232024"
    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)

    client = RateLimitedClient(
        # Stay polite even in the test runner — same defaults as
        # production. The smoke test is 3 GETs total so this doesn't
        # meaningfully slow us down.
        rate_per_sec=2.0,
        user_agent="PuckBunny-test/0.0 (smoke; contact: crenshaw.jonathan@gmail.com)",
        max_retries=3,
    )

    try:
        # Build the full collaborator set so the BackfillCollaborators
        # struct is structurally complete; only the season-summaries
        # loader actually runs.
        schedule_loader = ScheduleLoader(client)
        game_loader = GameLoader(client, storage)
        pbp_loader = PlayByPlayLoader(client, storage)
        daily_loader = DailyLoader(
            schedule_loader=schedule_loader,
            game_loader=game_loader,
            pbp_loader=pbp_loader,
            manifest=manifest,
        )
        season_summaries_loader = SeasonSummariesLoader(client, storage)
        team_season_loader = TeamSeasonLoader(client, storage)
        collaborators = BackfillCollaborators(
            daily_loader=daily_loader,
            season_summaries_loader=season_summaries_loader,
            team_season_loader=team_season_loader,
            manifest=manifest,
        )
        result = run_backfill(
            collaborators,
            seasons=[season],
            loader=PHASE_SEASON_SUMMARIES,
            cost_check_mode="off",
            ingest_date=date(2026, 5, 8),
            run_id="smoke-test",
        )
    finally:
        client.close()

    assert result.aborted is False
    phase = result.phase_results[0]
    assert phase.scope_units_loaded == 1
    assert phase.manifest_entries_appended == 3

    entries = manifest.read_entries()
    assert {e.endpoint for e in entries} == {
        SKATER_SUMMARY_ENDPOINT_TEMPLATE,
        GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
        TEAM_SUMMARY_ENDPOINT_TEMPLATE,
    }
    assert {e.scope_key for e in entries} == {season}
    # Each entry should record at least one row landing in bronze —
    # the live API never returns an empty `data` list for finalized
    # season totals.
    assert all(e.rows > 0 for e in entries)
    assert all(e.bytes > 0 for e in entries)
