"""Tests for ``puckbunny.ingestion.nhl.team_season`` and the
``team-season`` CLI.

Same cassette pattern as :mod:`tests.ingestion.test_nhl_games` and
:mod:`tests.ingestion.test_nhl_season_summaries`:
:class:`httpx.MockTransport` serves committed JSON fixtures from
``tests/ingestion/fixtures/team_season/``. The per-team endpoints
encode ``(team, season)`` in the URL path, so request matching is
path-based — we look up the response body keyed on the team
abbreviation parsed out of the path.

Target storage is :class:`puckbunny.storage.local.LocalFilesystemStorage`
under ``tmp_path``, exercising the same ``write_envelope_partition``
code path that R2 uses in production.
"""

from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from puckbunny.http.client import RateLimitedClient
from puckbunny.ingestion.nhl import cli as cli_module
from puckbunny.ingestion.nhl.endpoints import (
    CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
    ROSTER_ENDPOINT_TEMPLATE,
    club_schedule_season_url,
    roster_url,
    season_start_date,
    team_abbrevs,
)
from puckbunny.ingestion.nhl.team_season import (
    CLUB_SCHEDULE_SEASON_PARTITION_NAME,
    ROSTER_PARTITION_NAME,
    ClubScheduleSeasonMismatchError,
    TeamSeasonLoader,
)
from puckbunny.storage.local import LocalFilesystemStorage
from puckbunny.storage.parquet import ENVELOPE_SCHEMA

if TYPE_CHECKING:
    from collections.abc import Callable

_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "team_season"
_ROSTER_FIXTURE: Path = _FIXTURES_DIR / "roster_TOR_20242025.json"
_SCHEDULE_FIXTURE: Path = _FIXTURES_DIR / "club_schedule_season_TOR_20242025.json"
_SEASON: str = "20242025"
_TEAM: str = "TOR"


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _read_fixture(path: Path) -> bytes:
    """Read the fixture as bytes — preserves exact byte sequence so
    ``response_sha256`` is deterministic across runs."""
    return path.read_bytes()


def _make_handler(
    *,
    roster_body: bytes | None = None,
    schedule_body: bytes | None = None,
    roster_status: int = 200,
    schedule_status: int = 200,
    team: str = _TEAM,
    season: str = _SEASON,
    on_request: Callable[[httpx.Request], None] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a ``MockTransport`` handler keyed on the canonical roster
    and club-schedule-season URLs for ``(team, season)``.

    Defaults assume the TOR 2024-25 fixtures; tests that need a
    different team simply pass it through and the URL-matching follows.
    """
    roster_body = roster_body if roster_body is not None else _read_fixture(_ROSTER_FIXTURE)
    schedule_body = schedule_body if schedule_body is not None else _read_fixture(_SCHEDULE_FIXTURE)
    roster_target = roster_url(team, season)
    schedule_target = club_schedule_season_url(team, season)

    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        url = str(request.url)
        if url == roster_target:
            if roster_status == 200:
                return httpx.Response(
                    roster_status,
                    content=roster_body,
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(
                roster_status,
                content=b"<html>404</html>",
                headers={"content-type": "text/html"},
            )
        if url == schedule_target:
            if schedule_status == 200:
                return httpx.Response(
                    schedule_status,
                    content=schedule_body,
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(
                schedule_status,
                content=b"<html>404</html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(404, json={"error": "unmapped url", "url": url})

    return handler


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> RateLimitedClient:
    """Wrap ``handler`` in a fast, retry-light ``RateLimitedClient``."""
    return RateLimitedClient(
        rate_per_sec=100.0,
        user_agent="PuckBunny-test/0.0",
        max_retries=1,
        retry_initial_wait_seconds=0.0,
        retry_max_wait_seconds=0.0,
        transport=httpx.MockTransport(handler),
    )


def _read_envelope_table(storage: LocalFilesystemStorage, key: str) -> Any:
    return pq.read_table(  # type: ignore[no-untyped-call]
        io.BytesIO(storage.get_object(key))
    )


# --------------------------------------------------------------------
# TeamSeasonLoader.load_one — happy path
# --------------------------------------------------------------------


def test_load_one_writes_both_endpoints_to_separate_partitions(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_handler(on_request=requests_seen.append)

    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        result = loader.load_one(_SEASON, _TEAM, ingest_date=date(2026, 5, 4))

    assert result.season == _SEASON
    assert result.team == _TEAM
    assert result.roster is not None
    assert result.club_schedule_season is not None
    # Each endpoint goes to its own bronze partition.
    assert f"/nhl_api/{ROSTER_PARTITION_NAME}/ingest_date=2026-05-04/" in result.roster.key
    assert (
        f"/nhl_api/{CLUB_SCHEDULE_SEASON_PARTITION_NAME}/ingest_date=2026-05-04/"
        in result.club_schedule_season.key
    )
    # One bronze row per fetch (per-fetch granularity, see the loader
    # docstring's "Bronze row granularity" section).
    assert result.roster.rows == 1
    assert result.club_schedule_season.rows == 1
    # Both endpoints were called, in roster/schedule order.
    assert [str(r.url) for r in requests_seen] == [
        roster_url(_TEAM, _SEASON),
        club_schedule_season_url(_TEAM, _SEASON),
    ]


def test_load_one_envelope_columns_match_response(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()

    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        result = loader.load_one(_SEASON, _TEAM, ingest_date=date(2026, 5, 4))

    assert result.roster is not None
    roster_table = _read_envelope_table(storage, result.roster.key)
    assert roster_table.schema.equals(ENVELOPE_SCHEMA)
    # entity_id is the team abbreviation — the natural-key column for
    # per-team-per-season rows. The season column carries the requested
    # season; event_date is the Oct-1 sentinel.
    assert roster_table.column("entity_id").to_pylist() == [_TEAM]
    assert roster_table.column("season").to_pylist() == [_SEASON]
    assert roster_table.column("event_date").to_pylist() == [date(2024, 10, 1)]
    assert roster_table.column("endpoint").to_pylist() == [ROSTER_ENDPOINT_TEMPLATE]
    # response_json holds the verbatim API body — same verbatim
    # guarantee as PR-C/D/F1.
    rj = roster_table.column("response_json").to_pylist()[0]
    assert rj == _ROSTER_FIXTURE.read_text(encoding="utf-8")
    parsed = json.loads(rj)
    assert "forwards" in parsed and "defensemen" in parsed and "goalies" in parsed
    # endpoint_params_json captures the wire-truth dict.
    params = json.loads(roster_table.column("endpoint_params_json").to_pylist()[0])
    assert params == {"team": _TEAM, "season": _SEASON}

    # Spot-check the schedule endpoint landed at its template + entity_id.
    assert result.club_schedule_season is not None
    schedule_table = _read_envelope_table(storage, result.club_schedule_season.key)
    assert schedule_table.column("endpoint").to_pylist() == [CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE]
    assert schedule_table.column("entity_id").to_pylist() == [_TEAM]


def test_load_one_uses_today_when_ingest_date_omitted(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        result = loader.load_one(_SEASON, _TEAM)
    # Just check it landed in *some* ingest_date partition; we don't
    # assert the exact value to avoid a midnight-UTC flake.
    assert result.roster is not None and "/ingest_date=" in result.roster.key
    assert (
        result.club_schedule_season is not None
        and "/ingest_date=" in result.club_schedule_season.key
    )


def test_load_one_event_date_uses_season_start_sentinel(tmp_path: Path) -> None:
    """Confirm the Oct-1-of-start-year sentinel against the standalone
    helper — guards against the loader and helper drifting out of sync.
    Same shape as test_nhl_season_summaries' equivalent test.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()

    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        result = loader.load_one(_SEASON, _TEAM, ingest_date=date(2026, 5, 4))

    expected = season_start_date(_SEASON)
    assert expected == date(2024, 10, 1)
    assert result.roster is not None
    assert result.club_schedule_season is not None
    roster_table = _read_envelope_table(storage, result.roster.key)
    schedule_table = _read_envelope_table(storage, result.club_schedule_season.key)
    assert roster_table.column("event_date").to_pylist() == [expected]
    assert schedule_table.column("event_date").to_pylist() == [expected]


def test_load_one_normalizes_team_casing(tmp_path: Path) -> None:
    """Lower / mixed case team abbreviations should be upper-cased
    before any URL is built — handler still hits the canonical TOR URL.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        result = loader.load_one(_SEASON, "tor", ingest_date=date(2026, 5, 4))
    assert result.team == _TEAM


def test_load_one_accepts_int_season(tmp_path: Path) -> None:
    """Loader normalizes int seasons to str — both forms are valid."""
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        result = loader.load_one(20242025, _TEAM, ingest_date=date(2026, 5, 4))
    assert result.season == _SEASON


# --------------------------------------------------------------------
# 404 — log-and-skip
# --------------------------------------------------------------------


def test_load_one_logs_and_skips_on_roster_404(tmp_path: Path) -> None:
    """A 404 on the roster endpoint must surface as
    ``result.roster is None``, not raise. The schedule endpoint is
    independent and continues to fetch.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler(roster_status=404)
    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        result = loader.load_one(_SEASON, _TEAM, ingest_date=date(2026, 5, 4))

    assert result.roster is None
    # Schedule still succeeded — independent log-and-skip per endpoint.
    assert result.club_schedule_season is not None
    # No roster bronze rows.
    assert list(storage.list_objects(f"bronze/nhl_api/{ROSTER_PARTITION_NAME}")) == []


def test_load_one_logs_and_skips_on_both_404(tmp_path: Path) -> None:
    """Both endpoints 404 (e.g. UTA pre-2024-25): both slots are None."""
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler(roster_status=404, schedule_status=404)
    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        result = loader.load_one(_SEASON, _TEAM, ingest_date=date(2026, 5, 4))

    assert result.roster is None
    assert result.club_schedule_season is None
    # No bronze rows in either partition.
    assert list(storage.list_objects(f"bronze/nhl_api/{ROSTER_PARTITION_NAME}")) == []
    assert list(storage.list_objects(f"bronze/nhl_api/{CLUB_SCHEDULE_SEASON_PARTITION_NAME}")) == []


# --------------------------------------------------------------------
# Defensive invariants
# --------------------------------------------------------------------


def test_load_one_raises_on_currentseason_mismatch(tmp_path: Path) -> None:
    """If the schedule response's ``currentSeason`` differs from the
    requested season, refuse to write bronze.
    """
    storage = LocalFilesystemStorage(tmp_path)
    rewritten = json.loads(_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))
    rewritten["currentSeason"] = 20232024
    handler = _make_handler(schedule_body=json.dumps(rewritten).encode("utf-8"))

    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        with pytest.raises(ClubScheduleSeasonMismatchError, match="20232024"):
            loader.load_one(_SEASON, _TEAM, ingest_date=date(2026, 5, 4))

    # Roster wrote successfully (it was fetched first), schedule didn't.
    assert len(list(storage.list_objects(f"bronze/nhl_api/{ROSTER_PARTITION_NAME}"))) == 1
    assert list(storage.list_objects(f"bronze/nhl_api/{CLUB_SCHEDULE_SEASON_PARTITION_NAME}")) == []


def test_load_one_propagates_validation_error(tmp_path: Path) -> None:
    """A malformed roster response surfaces as ``ValidationError``."""
    storage = LocalFilesystemStorage(tmp_path)
    bad_body = json.dumps({"unexpected": "shape"}).encode("utf-8")
    handler = _make_handler(roster_body=bad_body)

    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        with pytest.raises(ValidationError):
            loader.load_one(_SEASON, _TEAM, ingest_date=date(2026, 5, 4))


def test_load_one_rejects_malformed_season(tmp_path: Path) -> None:
    """Season identifier must be 8 digits or YYYY-YY; non-conforming
    values raise before any I/O.

    Note: as of PR-G's D9 extension, ``"2024-25"`` IS accepted (and
    normalized to ``"20242025"`` before the wire call). The malformed
    case here is a clearly-bad value like ``"abcdefgh"`` that matches
    no input shape.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        with pytest.raises(ValueError, match="8 digits"):
            loader.load_one("abcdefgh", _TEAM, ingest_date=date(2026, 5, 4))


def test_load_one_rejects_malformed_team(tmp_path: Path) -> None:
    """Team must be a 3-letter abbreviation; other shapes raise early."""
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    with _make_client(handler) as client:
        loader = TeamSeasonLoader(client, storage)
        with pytest.raises(ValueError, match="3-letter"):
            loader.load_one(_SEASON, "Toronto", ingest_date=date(2026, 5, 4))


# --------------------------------------------------------------------
# Endpoint-level helpers (team_abbrevs)
# --------------------------------------------------------------------


def test_team_abbrevs_2015_2017_is_30_team_base() -> None:
    """First two backfill seasons predate VGK/SEA/UTA → 30 teams."""
    assert len(team_abbrevs("20152016")) == 30
    assert len(team_abbrevs("20162017")) == 30
    # ARI present, UTA absent.
    assert "ARI" in team_abbrevs("20152016")
    assert "UTA" not in team_abbrevs("20152016")
    # WPG (relocated from ATL in 2011-12) is present.
    assert "WPG" in team_abbrevs("20152016")


def test_team_abbrevs_adds_vgk_in_2017_18() -> None:
    """Vegas joined as expansion in 2017-18."""
    assert "VGK" not in team_abbrevs("20162017")
    assert "VGK" in team_abbrevs("20172018")
    assert len(team_abbrevs("20172018")) == 31


def test_team_abbrevs_adds_sea_in_2021_22() -> None:
    """Seattle joined as expansion in 2021-22."""
    assert "SEA" not in team_abbrevs("20202021")
    assert "SEA" in team_abbrevs("20212022")
    assert len(team_abbrevs("20212022")) == 32


def test_team_abbrevs_swaps_ari_to_uta_in_2024_25() -> None:
    """Arizona Coyotes franchise relocated to Utah for 2024-25."""
    assert "ARI" in team_abbrevs("20232024")
    assert "UTA" not in team_abbrevs("20232024")
    assert "ARI" not in team_abbrevs("20242025")
    assert "UTA" in team_abbrevs("20242025")
    # Membership count stays at 32 — relocation, not expansion.
    assert len(team_abbrevs("20242025")) == 32


# --------------------------------------------------------------------
# CLI: python -m puckbunny.ingestion.nhl team-season --season ... --team ...
# --------------------------------------------------------------------


def test_cli_team_season_subcommand_end_to_end(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main(["team-season", "--season", ..., "--team", ...])`` runs
    through the full fetch+write path with mocked transport and prints
    a JSON summary.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    client = _make_client(handler)

    def factory(_args: object) -> tuple[TeamSeasonLoader, Callable[[], None]]:
        return TeamSeasonLoader(client, storage), client.close

    exit_code = cli_module.main(
        [
            "team-season",
            "--season",
            _SEASON,
            "--team",
            _TEAM,
            "--ingest-date",
            "2026-05-04",
            "--log-level",
            "WARNING",
        ],
        team_season_loader_factory=factory,
    )
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    summary = json.loads(out)
    assert summary["season"] == _SEASON
    assert len(summary["teams"]) == 1
    team_entry = summary["teams"][0]
    assert team_entry["team"] == _TEAM
    assert ROSTER_PARTITION_NAME in team_entry["roster"]["key"]
    assert CLUB_SCHEDULE_SEASON_PARTITION_NAME in team_entry["club_schedule_season"]["key"]
    assert team_entry["roster"]["rows"] == 1
    assert team_entry["club_schedule_season"]["rows"] == 1


def test_cli_team_season_omitting_team_iterates_season_membership(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--team`` omitted → CLI iterates ``team_abbrevs(season)``. We
    use a handler that returns the TOR fixture for any team URL to
    keep the test cheap; the routing key here is just whether the
    request was made, not which team's data came back.
    """
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        # Return the TOR fixture for any team URL — we don't care which
        # team's payload comes back; we only assert the *count* of
        # requests matches the season's membership.
        path = request.url.path
        if "/v1/roster/" in path:
            return httpx.Response(
                200,
                content=_read_fixture(_ROSTER_FIXTURE),
                headers={"content-type": "application/json"},
            )
        if "/v1/club-schedule-season/" in path:
            return httpx.Response(
                200,
                content=_read_fixture(_SCHEDULE_FIXTURE),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, json={"error": "unmapped path", "path": path})

    client = RateLimitedClient(
        rate_per_sec=100.0,
        user_agent="PuckBunny-test/0.0",
        max_retries=1,
        retry_initial_wait_seconds=0.0,
        retry_max_wait_seconds=0.0,
        transport=httpx.MockTransport(handler),
    )

    def factory(_args: object) -> tuple[TeamSeasonLoader, Callable[[], None]]:
        return TeamSeasonLoader(client, storage), client.close

    # NB: the schedule fixture's currentSeason==20242025; using a
    # different season here would trip the mismatch invariant. So we
    # use 20242025 for this test.
    exit_code = cli_module.main(
        [
            "team-season",
            "--season",
            _SEASON,
            "--ingest-date",
            "2026-05-04",
            "--log-level",
            "WARNING",
        ],
        team_season_loader_factory=factory,
    )
    assert exit_code == 0

    expected_team_count = len(team_abbrevs(_SEASON))  # 32 for 2024-25
    out = capsys.readouterr().out.strip()
    summary = json.loads(out)
    assert summary["season"] == _SEASON
    assert len(summary["teams"]) == expected_team_count
    # Two GETs per team (roster + schedule).
    assert len(requests_seen) == expected_team_count * 2


def test_cli_rejects_missing_season(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--season`` is required; argparse should error before any I/O."""
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main(["team-season"])
    # argparse exits with code 2 on usage errors.
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--season" in err
