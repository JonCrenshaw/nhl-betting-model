"""End-to-end resume test for the backfill orchestrator.

Where ``test_backfill.py`` covers orchestrator semantics with stubbed
loaders, this module exercises the *real* loaders against
``LocalFilesystemStorage`` + ``httpx.MockTransport``. The job is to
prove three properties end-to-end:

1. **Initial run** produces the expected bronze partitions and
   manifest entries.
2. **Repeat run** is a no-op — the manifest gates every scope unit,
   no HTTP calls happen, and no new manifest entries land.
3. **Partial-manifest delete** re-fetches the affected scope unit
   only, per D11's "any missing → re-fetch both" rule.

Scope is intentionally narrow — ``team-season`` only, one season, one
team. The unit tests already cover orchestrator dispatch + cost-check;
this test's value-add is that the real serialization round-trip
(Parquet write + JSONL append + JSONL parse) preserves manifest gating
across orchestrator invocations. ``team_abbrevs`` is monkeypatched to
``{"TOR"}`` so we don't need fixtures for the other 31 teams; the
existing TOR 2024-25 fixtures from ``test_nhl_team_season.py`` carry
the test.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from puckbunny.http.client import RateLimitedClient
from puckbunny.ingestion.manifest import ManifestEntry, ManifestStore
from puckbunny.ingestion.nhl.backfill import (
    PHASE_TEAM_SEASON,
    BackfillCollaborators,
    run_backfill,
)
from puckbunny.ingestion.nhl.endpoints import (
    CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
    ROSTER_ENDPOINT_TEMPLATE,
    club_schedule_season_url,
    roster_url,
)
from puckbunny.ingestion.nhl.games import GameLoader
from puckbunny.ingestion.nhl.play_by_play import PlayByPlayLoader
from puckbunny.ingestion.nhl.schedule import (
    DailyLoader,
    ScheduleLoader,
)
from puckbunny.ingestion.nhl.season_summaries import SeasonSummariesLoader
from puckbunny.ingestion.nhl.team_season import TeamSeasonLoader
from puckbunny.storage.local import LocalFilesystemStorage

if TYPE_CHECKING:
    from collections.abc import Callable


_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "team_season"
_ROSTER_FIXTURE: Path = _FIXTURES_DIR / "roster_TOR_20242025.json"
_SCHEDULE_FIXTURE: Path = _FIXTURES_DIR / "club_schedule_season_TOR_20242025.json"

_SEASON: str = "20242025"
_TEAM: str = "TOR"
_INGEST_DATE: date = date(2026, 5, 8)


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _read_fixture(path: Path) -> bytes:
    return path.read_bytes()


def _make_handler(
    *,
    requests_seen: list[httpx.Request],
) -> Callable[[httpx.Request], httpx.Response]:
    """Mock-transport handler keyed on the canonical URLs for TOR
    2024-25. Records every request into ``requests_seen`` so tests can
    assert exact-fetch counts after each run."""
    roster_body = _read_fixture(_ROSTER_FIXTURE)
    schedule_body = _read_fixture(_SCHEDULE_FIXTURE)
    roster_target = roster_url(_TEAM, _SEASON)
    schedule_target = club_schedule_season_url(_TEAM, _SEASON)

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        url = str(request.url)
        if url == roster_target:
            return httpx.Response(
                200, content=roster_body, headers={"content-type": "application/json"}
            )
        if url == schedule_target:
            return httpx.Response(
                200,
                content=schedule_body,
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, json={"error": "unmapped url", "url": url})

    return handler


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> RateLimitedClient:
    return RateLimitedClient(
        rate_per_sec=100.0,
        user_agent="PuckBunny-test/0.0",
        max_retries=1,
        retry_initial_wait_seconds=0.0,
        retry_max_wait_seconds=0.0,
        transport=httpx.MockTransport(handler),
    )


def _make_collaborators(
    client: RateLimitedClient, storage: LocalFilesystemStorage
) -> tuple[BackfillCollaborators, ManifestStore]:
    """Wire real loaders + manifest, mirroring the production factory
    structure but pointing at local storage + the test client. The
    games-phase loaders (DailyLoader, ScheduleLoader) are wired here
    even though we only run the team-season phase, so the
    BackfillCollaborators struct is structurally complete."""
    schedule_loader = ScheduleLoader(client)
    game_loader = GameLoader(client, storage)
    pbp_loader = PlayByPlayLoader(client, storage)
    manifest = ManifestStore(storage)
    daily_loader = DailyLoader(
        schedule_loader=schedule_loader,
        game_loader=game_loader,
        pbp_loader=pbp_loader,
        manifest=manifest,
    )
    season_summaries_loader = SeasonSummariesLoader(client, storage)
    team_season_loader = TeamSeasonLoader(client, storage)
    return BackfillCollaborators(
        daily_loader=daily_loader,
        season_summaries_loader=season_summaries_loader,
        team_season_loader=team_season_loader,
        manifest=manifest,
    ), manifest


# --------------------------------------------------------------------
# End-to-end resume scenarios
# --------------------------------------------------------------------


@pytest.fixture
def _scope_team_abbrevs_to_tor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch ``team_abbrevs`` in :mod:`puckbunny.ingestion.nhl.backfill`
    to return only ``{"TOR"}`` for any season.

    Avoids the need for fixtures for the other 31 teams in 2024-25
    while still exercising the orchestrator's full team-iteration code
    path (it just iterates a one-element set).
    """
    monkeypatch.setattr(
        "puckbunny.ingestion.nhl.backfill.team_abbrevs",
        lambda _season: frozenset({"TOR"}),
    )


def test_initial_run_produces_bronze_and_manifest(
    tmp_path: Path,
    _scope_team_abbrevs_to_tor: None,
) -> None:
    """First invocation: 2 HTTP fetches (roster + club-schedule), 2
    bronze partitions written, 2 manifest entries appended."""
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_handler(requests_seen=requests_seen)
    with _make_client(handler) as client:
        collaborators, manifest = _make_collaborators(client, storage)
        result = run_backfill(
            collaborators,
            seasons=[_SEASON],
            loader=PHASE_TEAM_SEASON,
            cost_check_mode="off",
            ingest_date=_INGEST_DATE,
            run_id="initial-run",
        )

    assert result.aborted is False
    assert len(result.phase_results) == 1
    phase = result.phase_results[0]
    assert phase.phase == PHASE_TEAM_SEASON
    assert phase.scope_units_attempted == 1
    assert phase.scope_units_loaded == 1
    assert phase.scope_units_skipped == 0
    assert phase.manifest_entries_appended == 2

    # 2 fetches landed (roster + club-schedule).
    assert len(requests_seen) == 2

    # Manifest reflects exactly those two endpoints, scoped to TOR
    # 2024-25, stamped with the supplied run_id.
    entries = manifest.read_entries()
    assert len(entries) == 2
    assert {e.endpoint for e in entries} == {
        ROSTER_ENDPOINT_TEMPLATE,
        CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
    }
    assert {e.scope_key for e in entries} == {f"{_SEASON}|{_TEAM}"}
    assert {e.run_id for e in entries} == {"initial-run"}


def test_repeat_run_is_a_no_op(
    tmp_path: Path,
    _scope_team_abbrevs_to_tor: None,
) -> None:
    """Re-invoking with the same arguments after a successful initial
    run: zero HTTP fetches, zero new manifest entries. Exactly the
    property an interrupted backfill needs to resume cleanly."""
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_handler(requests_seen=requests_seen)

    with _make_client(handler) as client:
        collaborators, manifest = _make_collaborators(client, storage)
        run_backfill(
            collaborators,
            seasons=[_SEASON],
            loader=PHASE_TEAM_SEASON,
            cost_check_mode="off",
            ingest_date=_INGEST_DATE,
            run_id="initial-run",
        )

    initial_request_count = len(requests_seen)
    initial_entries = manifest.read_entries()

    # Second invocation — fresh client, but the manifest persists in
    # storage so the orchestrator should skip the only scope unit.
    with _make_client(handler) as client2:
        collaborators2, manifest2 = _make_collaborators(client2, storage)
        result = run_backfill(
            collaborators2,
            seasons=[_SEASON],
            loader=PHASE_TEAM_SEASON,
            cost_check_mode="off",
            ingest_date=_INGEST_DATE,
            run_id="repeat-run",
        )

    # Phase summary reflects the skip.
    phase = result.phase_results[0]
    assert phase.scope_units_attempted == 1
    assert phase.scope_units_skipped == 1
    assert phase.scope_units_loaded == 0
    assert phase.manifest_entries_appended == 0

    # No new HTTP calls.
    assert len(requests_seen) == initial_request_count

    # Manifest unchanged.
    assert manifest2.read_entries() == initial_entries


def test_partial_manifest_delete_refetches_only_affected_scope(
    tmp_path: Path,
    _scope_team_abbrevs_to_tor: None,
) -> None:
    """Delete the club-schedule manifest entry from a fully-loaded
    manifest, run again: the orchestrator re-fetches BOTH endpoints
    (per D11's "any missing → re-fetch both"), writing a duplicate
    roster entry alongside the new club-schedule entry. Other scope
    units are unaffected.
    """
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_handler(requests_seen=requests_seen)

    # Initial full run.
    with _make_client(handler) as client:
        collaborators, manifest = _make_collaborators(client, storage)
        run_backfill(
            collaborators,
            seasons=[_SEASON],
            loader=PHASE_TEAM_SEASON,
            cost_check_mode="off",
            ingest_date=_INGEST_DATE,
            run_id="initial-run",
        )
    initial_request_count = len(requests_seen)
    assert initial_request_count == 2

    # Surgically delete the club-schedule entry — write the manifest
    # back without it. Keeps the roster entry, which leaves the scope
    # unit "partial" per the gating rule.
    keep: list[ManifestEntry] = [
        e for e in manifest.read_entries() if e.endpoint != CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE
    ]
    storage.put_object(
        manifest.key,
        b"".join(e.to_jsonl_line().encode("utf-8") for e in keep),
        content_type="application/x-ndjson",
    )

    # Resume run.
    with _make_client(handler) as client2:
        collaborators2, manifest2 = _make_collaborators(client2, storage)
        result = run_backfill(
            collaborators2,
            seasons=[_SEASON],
            loader=PHASE_TEAM_SEASON,
            cost_check_mode="off",
            ingest_date=_INGEST_DATE,
            run_id="resume-run",
        )

    phase = result.phase_results[0]
    assert phase.scope_units_loaded == 1  # Re-fetched the partial unit.
    assert phase.scope_units_skipped == 0
    assert phase.manifest_entries_appended == 2  # Both endpoints re-written.

    # Two new fetches (both endpoints re-fetched per D11) — total 4.
    assert len(requests_seen) - initial_request_count == 2

    # Manifest now has the original roster + a new roster + a new
    # club-schedule = 3 entries. The duplicate roster is intentional
    # per D11's tradeoff (per-endpoint dedupe was rejected).
    entries = manifest2.read_entries()
    assert len(entries) == 3
    roster_entries = [e for e in entries if e.endpoint == ROSTER_ENDPOINT_TEMPLATE]
    club_schedule_entries = [
        e for e in entries if e.endpoint == CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE
    ]
    assert len(roster_entries) == 2
    assert len(club_schedule_entries) == 1

    # The new entries carry the resume run_id; the original carries
    # the initial run_id. Lets ops queries distinguish "from which
    # backfill run did this entry land".
    assert {e.run_id for e in roster_entries} == {"initial-run", "resume-run"}
    assert {e.run_id for e in club_schedule_entries} == {"resume-run"}
