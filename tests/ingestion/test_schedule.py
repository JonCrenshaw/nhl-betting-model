"""Tests for ``puckbunny.ingestion.nhl.schedule`` and the ``daily`` CLI.

Same cassette pattern as ``test_nhl_games.py`` and ``test_nhl_pbp.py``
— ``httpx.MockTransport`` serves the recorded fixtures, storage is
:class:`puckbunny.storage.local.LocalFilesystemStorage` under
``tmp_path``. The schedule fixture
(``fixtures/schedule/schedule_2026-04-24.json``) is hand-crafted to
exercise every branch of the daily walker:

* one ``OFF`` game on the target date that matches the existing
  game-level fixtures (``2025030123``) — must be ingested,
* one ``LIVE`` game on the target date — must be skipped,
* one ``FUT`` game on the target date — must be skipped,
* one ``OFF`` game on a different date inside the same ``gameWeek``
  — must be skipped by ``select_day``.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import httpx
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from puckbunny.http.client import RateLimitedClient
from puckbunny.ingestion.manifest import (
    DEFAULT_MANIFEST_KEY,
    ManifestStore,
    build_entry,
)
from puckbunny.ingestion.nhl import cli as cli_module
from puckbunny.ingestion.nhl.endpoints import (
    BOXSCORE_ENDPOINT_TEMPLATE,
    LANDING_ENDPOINT_TEMPLATE,
    PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
    boxscore_url,
    landing_url,
    play_by_play_url,
    schedule_url,
)
from puckbunny.ingestion.nhl.games import GameLoader
from puckbunny.ingestion.nhl.play_by_play import PlayByPlayLoader
from puckbunny.ingestion.nhl.schedule import (
    DailyLoader,
    ScheduleDayNotFoundError,
    ScheduleLoader,
    filter_ingestible,
    select_day,
    yesterday_in_toronto,
)
from puckbunny.ingestion.nhl.schemas import ScheduleResponse
from puckbunny.storage.local import LocalFilesystemStorage

if TYPE_CHECKING:
    from collections.abc import Callable

_SCHEDULE_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "schedule"
_GAMES_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "games"

_SCHEDULE_FIXTURE: Path = _SCHEDULE_FIXTURES_DIR / "schedule_2026-04-24.json"
_LANDING_FIXTURE: Path = _GAMES_FIXTURES_DIR / "landing_2025030123.json"
_BOXSCORE_FIXTURE: Path = _GAMES_FIXTURES_DIR / "boxscore_2025030123.json"
_PBP_FIXTURE: Path = _GAMES_FIXTURES_DIR / "play_by_play_2025030123.json"

_TARGET_DATE: date = date(2026, 4, 24)
_INGEST_DATE: date = date(2026, 4, 25)
_GAME_ID: int = 2025030123


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _make_full_handler(
    *,
    schedule_body: bytes | None = None,
    on_request: Callable[[httpx.Request], None] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Map all four URLs (schedule + 3 game endpoints) to fixtures.

    Used by end-to-end tests where the ``DailyLoader`` walks the
    schedule, then fetches landing/boxscore/play-by-play for the one
    eligible game on the target date.
    """
    schedule_body = schedule_body if schedule_body is not None else _read(_SCHEDULE_FIXTURE)
    landing_body = _read(_LANDING_FIXTURE)
    boxscore_body = _read(_BOXSCORE_FIXTURE)
    pbp_body = _read(_PBP_FIXTURE)

    schedule_target = schedule_url(_TARGET_DATE)
    landing_target = landing_url(_GAME_ID)
    boxscore_target = boxscore_url(_GAME_ID)
    pbp_target = play_by_play_url(_GAME_ID)

    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        url = str(request.url)
        if url == schedule_target:
            return httpx.Response(
                200, content=schedule_body, headers={"content-type": "application/json"}
            )
        if url == landing_target:
            return httpx.Response(
                200, content=landing_body, headers={"content-type": "application/json"}
            )
        if url == boxscore_target:
            return httpx.Response(
                200, content=boxscore_body, headers={"content-type": "application/json"}
            )
        if url == pbp_target:
            return httpx.Response(
                200, content=pbp_body, headers={"content-type": "application/json"}
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


def _read_envelope_table(storage: LocalFilesystemStorage, key: str) -> Any:
    return pq.read_table(  # type: ignore[no-untyped-call]
        io.BytesIO(storage.get_object(key))
    )


def _build_daily_loader(
    client: RateLimitedClient,
    storage: LocalFilesystemStorage,
) -> DailyLoader:
    schedule_loader = ScheduleLoader(client)
    game_loader = GameLoader(client, storage)
    pbp_loader = PlayByPlayLoader(client, storage)
    manifest = ManifestStore(storage)
    return DailyLoader(
        schedule_loader=schedule_loader,
        game_loader=game_loader,
        pbp_loader=pbp_loader,
        manifest=manifest,
    )


# --------------------------------------------------------------------
# ScheduleResponse parses the fixture
# --------------------------------------------------------------------


def test_schedule_fixture_parses() -> None:
    payload = json.loads(_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))
    parsed = ScheduleResponse.model_validate(payload)
    assert len(parsed.gameWeek) == 3
    assert [d.date.isoformat() for d in parsed.gameWeek] == [
        "2026-04-23",
        "2026-04-24",
        "2026-04-25",
    ]
    # The 04-24 day has three games (OFF + LIVE + FUT).
    target_day = parsed.gameWeek[1]
    assert target_day.date == _TARGET_DATE
    assert len(target_day.games) == 3
    states = {g.gameState for g in target_day.games}
    assert states == {"OFF", "LIVE", "FUT"}


# --------------------------------------------------------------------
# select_day / filter_ingestible
# --------------------------------------------------------------------


def test_select_day_returns_matching_entry() -> None:
    payload = json.loads(_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))
    schedule = ScheduleResponse.model_validate(payload)
    day = select_day(schedule, _TARGET_DATE)
    assert day.date == _TARGET_DATE
    assert len(day.games) == 3


def test_select_day_raises_when_target_missing() -> None:
    payload = json.loads(_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))
    schedule = ScheduleResponse.model_validate(payload)
    with pytest.raises(ScheduleDayNotFoundError, match="2030-01-01"):
        select_day(schedule, date(2030, 1, 1))


def test_filter_ingestible_keeps_only_final_and_off() -> None:
    payload = json.loads(_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))
    schedule = ScheduleResponse.model_validate(payload)
    day = select_day(schedule, _TARGET_DATE)
    eligible = filter_ingestible(day.games)
    # Only the OFF game should remain on the target date.
    assert [g.id for g in eligible] == [_GAME_ID]


def test_filter_ingestible_preserves_order() -> None:
    """Order matters — the daily walker uses the schedule's natural
    ordering (typically ``startTimeUTC``)."""
    payload = json.loads(_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))
    schedule = ScheduleResponse.model_validate(payload)
    day = select_day(schedule, _TARGET_DATE)
    # Synthetically mark all three target-date games as OFF — order
    # of the input list should be preserved on the output.
    for g in day.games:
        # Pydantic frozen=False on these models so we can mutate.
        g.gameState = "OFF"  # type: ignore[misc]
    eligible = filter_ingestible(day.games)
    assert [g.id for g in eligible] == [g.id for g in day.games]


# --------------------------------------------------------------------
# ScheduleLoader.fetch
# --------------------------------------------------------------------


def test_schedule_loader_fetch_validates_response(tmp_path: Path) -> None:
    handler = _make_full_handler()
    with _make_client(handler) as client:
        loader = ScheduleLoader(client)
        schedule = loader.fetch(_TARGET_DATE)
    assert len(schedule.gameWeek) == 3


def test_schedule_loader_fetch_propagates_validation_error() -> None:
    """Malformed response → ValidationError, not a half-shaped object."""
    bad = json.dumps({"gameWeek": [{"date": "not-a-date", "games": []}]}).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bad, headers={"content-type": "application/json"})

    with _make_client(handler) as client:
        loader = ScheduleLoader(client)
        with pytest.raises(ValidationError):
            loader.fetch(_TARGET_DATE)


# --------------------------------------------------------------------
# DailyLoader.load_date — happy path
# --------------------------------------------------------------------


def test_daily_load_writes_one_game_and_skips_the_rest(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_full_handler(on_request=requests_seen.append)

    with _make_client(handler) as client:
        loader = _build_daily_loader(client, storage)
        result = loader.load_date(_TARGET_DATE, ingest_date=_INGEST_DATE)

    # Schedule said: 3 games on 04-24, one of which is OFF; the 04-23
    # day's OFF game is excluded by date.
    assert result.target_date == _TARGET_DATE
    assert result.ingest_date == _INGEST_DATE
    assert result.games_in_schedule == 3
    assert result.games_eligible == 1
    assert result.games_loaded == 1
    assert result.games_skipped == 0
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.game_id == _GAME_ID
    assert outcome.skipped is False
    assert outcome.landing is not None
    assert outcome.boxscore is not None
    assert outcome.play_by_play is not None

    # We hit exactly four URLs: schedule + the three game-level endpoints.
    urls_called = [str(r.url) for r in requests_seen]
    assert urls_called == [
        schedule_url(_TARGET_DATE),
        landing_url(_GAME_ID),
        boxscore_url(_GAME_ID),
        play_by_play_url(_GAME_ID),
    ]

    # Bronze partitions populated for all three endpoints.
    assert f"/nhl_api/landing/ingest_date={_INGEST_DATE.isoformat()}/" in outcome.landing.key
    assert f"/nhl_api/boxscore/ingest_date={_INGEST_DATE.isoformat()}/" in outcome.boxscore.key
    assert (
        f"/nhl_api/play-by-play/ingest_date={_INGEST_DATE.isoformat()}/" in outcome.play_by_play.key
    )

    # The bronze envelope is the same shape as the per-endpoint loaders
    # produce — sanity: response_json on landing matches the fixture
    # bytes.
    landing_table = _read_envelope_table(storage, outcome.landing.key)
    rj = landing_table.column("response_json").to_pylist()[0]
    assert rj == _LANDING_FIXTURE.read_text(encoding="utf-8")


def test_daily_load_records_three_manifest_entries_per_game(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_full_handler()
    with _make_client(handler) as client:
        loader = _build_daily_loader(client, storage)
        result = loader.load_date(_TARGET_DATE, ingest_date=_INGEST_DATE)

    manifest = ManifestStore(storage)
    entries = manifest.read_entries()
    # One entry per (endpoint, game) for the single ingested game.
    assert len(entries) == 3
    endpoints = {e.endpoint for e in entries}
    assert endpoints == {
        LANDING_ENDPOINT_TEMPLATE,
        BOXSCORE_ENDPOINT_TEMPLATE,
        PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
    }
    # All entries share the run_id from the result.
    assert {e.run_id for e in entries} == {result.run_id}
    # All scope_keys point at the one ingested game.
    assert {e.scope_key for e in entries} == {str(_GAME_ID)}


# --------------------------------------------------------------------
# DailyLoader.load_date — idempotency via manifest
# --------------------------------------------------------------------


def test_daily_load_skips_games_already_in_manifest(tmp_path: Path) -> None:
    """Pre-seed the manifest with all three endpoints for the eligible
    game; the loader must skip the game and make no game-level HTTP
    calls (only the schedule call)."""
    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)
    for endpoint in (
        LANDING_ENDPOINT_TEMPLATE,
        BOXSCORE_ENDPOINT_TEMPLATE,
        PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
    ):
        manifest.append(
            build_entry(
                run_id="prior-run",
                endpoint=endpoint,
                scope_key=str(_GAME_ID),
                rows=1,
                bytes_written=1000,
            )
        )

    requests_seen: list[httpx.Request] = []
    handler = _make_full_handler(on_request=requests_seen.append)
    with _make_client(handler) as client:
        loader = _build_daily_loader(client, storage)
        result = loader.load_date(_TARGET_DATE, ingest_date=_INGEST_DATE)

    assert result.games_loaded == 0
    assert result.games_skipped == 1
    assert result.outcomes[0].skipped is True
    # Only the schedule URL should have been hit.
    assert [str(r.url) for r in requests_seen] == [schedule_url(_TARGET_DATE)]

    # Manifest count unchanged — the skipped game adds no new entries.
    assert len(ManifestStore(storage).read_entries()) == 3


def test_daily_load_refetches_game_when_any_endpoint_missing(tmp_path: Path) -> None:
    """If only some endpoints are present in the manifest, the
    orchestrator re-fetches all three. Documented in
    ``schedule.py`` module docstring as the simplicity tradeoff."""
    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)
    # Only landing pre-recorded.
    manifest.append(
        build_entry(
            run_id="prior-run",
            endpoint=LANDING_ENDPOINT_TEMPLATE,
            scope_key=str(_GAME_ID),
            rows=1,
            bytes_written=1000,
        )
    )

    requests_seen: list[httpx.Request] = []
    handler = _make_full_handler(on_request=requests_seen.append)
    with _make_client(handler) as client:
        loader = _build_daily_loader(client, storage)
        result = loader.load_date(_TARGET_DATE, ingest_date=_INGEST_DATE)

    assert result.games_loaded == 1
    assert result.games_skipped == 0
    # All three game-level URLs were called again.
    urls = [str(r.url) for r in requests_seen]
    assert landing_url(_GAME_ID) in urls
    assert boxscore_url(_GAME_ID) in urls
    assert play_by_play_url(_GAME_ID) in urls


# --------------------------------------------------------------------
# DailyLoader.load_date — empty / weird cases
# --------------------------------------------------------------------


def test_daily_load_with_no_eligible_games(tmp_path: Path) -> None:
    """All FUT/LIVE on the target date: nothing fetched, nothing in manifest."""
    storage = LocalFilesystemStorage(tmp_path)
    # Synthesize a schedule where the target day has only LIVE games.
    payload = json.loads(_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))
    target_day = next(d for d in payload["gameWeek"] if d["date"] == _TARGET_DATE.isoformat())
    for g in target_day["games"]:
        g["gameState"] = "LIVE"
    bad_schedule = json.dumps(payload).encode("utf-8")

    handler = _make_full_handler(schedule_body=bad_schedule)
    with _make_client(handler) as client:
        loader = _build_daily_loader(client, storage)
        result = loader.load_date(_TARGET_DATE, ingest_date=_INGEST_DATE)

    assert result.games_in_schedule == 3
    assert result.games_eligible == 0
    assert result.games_loaded == 0
    assert result.games_skipped == 0
    assert result.outcomes == []
    # No manifest writes.
    assert ManifestStore(storage).read_entries() == []


# --------------------------------------------------------------------
# yesterday_in_toronto
# --------------------------------------------------------------------


def test_yesterday_in_toronto_returns_prior_eastern_date() -> None:
    # Production scenario: daily job runs at 07:00 UTC = 03:00 EDT
    # the same Toronto morning, and needs to ingest the previous
    # Eastern day's slate. "Yesterday in Toronto" from 04-25 03:00 EDT
    # is 04-24 — the game date for our fixture.
    fixed_now = datetime(2026, 4, 25, 7, 0, tzinfo=UTC)
    assert yesterday_in_toronto(now=fixed_now) == date(2026, 4, 24)


def test_yesterday_in_toronto_handles_morning_eastern() -> None:
    # 2026-04-25 12:00 UTC = 08:00 EDT — yesterday in Toronto is 04-24.
    fixed_now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    assert yesterday_in_toronto(now=fixed_now) == date(2026, 4, 24)


def test_yesterday_in_toronto_accepts_naive_input() -> None:
    """Naive ``now`` must not silently coerce to UTC — assume Toronto."""
    naive = datetime(2026, 4, 25, 2, 0)  # naive
    # Treated as Toronto local: 02:00 ET → yesterday is 04-24.
    assert yesterday_in_toronto(now=naive) == date(2026, 4, 24)


def test_yesterday_in_toronto_uses_zoneinfo() -> None:
    """Sanity: the helper actually consults Toronto's DST rules.
    A wall-clock instant just after midnight ET should still report
    yesterday relative to the Eastern day, not the UTC day."""
    # 2026-04-24 04:00 UTC = 2026-04-24 00:00 ET (DST). Yesterday = 04-23.
    instant = datetime(2026, 4, 24, 4, 0, tzinfo=UTC)
    expected = (instant.astimezone(ZoneInfo("America/Toronto")).date()) - (
        datetime(2026, 4, 24).date() - datetime(2026, 4, 23).date()
    )
    assert yesterday_in_toronto(now=instant) == expected


# --------------------------------------------------------------------
# CLI: python -m puckbunny.ingestion.nhl daily ...
# --------------------------------------------------------------------


def test_cli_daily_subcommand_end_to_end(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main(["daily", "--date", ...])`` runs the full schedule →
    games+pbp pipeline with mocked transport and prints a JSON
    summary."""
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_full_handler()
    client = _make_client(handler)

    def factory(_args: object) -> tuple[DailyLoader, Callable[[], None]]:
        return _build_daily_loader(client, storage), client.close

    exit_code = cli_module.main(
        [
            "daily",
            "--date",
            _TARGET_DATE.isoformat(),
            "--ingest-date",
            _INGEST_DATE.isoformat(),
            "--log-level",
            "WARNING",
        ],
        daily_loader_factory=factory,
    )
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    summary = json.loads(out)
    assert summary["target_date"] == _TARGET_DATE.isoformat()
    assert summary["ingest_date"] == _INGEST_DATE.isoformat()
    assert summary["games_in_schedule"] == 3
    assert summary["games_eligible"] == 1
    assert summary["games_loaded"] == 1
    assert summary["games_skipped"] == 0
    assert len(summary["games"]) == 1
    g = summary["games"][0]
    assert g["game_id"] == _GAME_ID
    assert g["skipped"] is False
    assert "landing" in g["landing_key"]
    assert "boxscore" in g["boxscore_key"]
    assert "play-by-play" in g["play_by_play_key"]


def test_cli_daily_subcommand_skipped_game_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the eligible game is already in the manifest, the summary
    must mark it skipped (no key fields)."""
    storage = LocalFilesystemStorage(tmp_path)
    manifest = ManifestStore(storage)
    for endpoint in (
        LANDING_ENDPOINT_TEMPLATE,
        BOXSCORE_ENDPOINT_TEMPLATE,
        PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
    ):
        manifest.append(
            build_entry(
                run_id="prior-run",
                endpoint=endpoint,
                scope_key=str(_GAME_ID),
                rows=1,
                bytes_written=1000,
            )
        )

    handler = _make_full_handler()
    client = _make_client(handler)

    def factory(_args: object) -> tuple[DailyLoader, Callable[[], None]]:
        return _build_daily_loader(client, storage), client.close

    exit_code = cli_module.main(
        [
            "daily",
            "--date",
            _TARGET_DATE.isoformat(),
            "--ingest-date",
            _INGEST_DATE.isoformat(),
            "--log-level",
            "WARNING",
        ],
        daily_loader_factory=factory,
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["games_loaded"] == 0
    assert summary["games_skipped"] == 1
    g = summary["games"][0]
    assert g == {"game_id": _GAME_ID, "skipped": True}


def test_cli_daily_rejects_invalid_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``argparse`` must reject malformed ``--date`` before any IO."""
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main(["daily", "--date", "not-a-date"])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--date" in err or "date" in err


def test_cli_daily_default_date_is_yesterday_toronto(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitting ``--date`` should call ``yesterday_in_toronto`` and
    fetch the schedule for that date. We monkeypatch the helper to a
    fixed value so the test isn't time-dependent."""
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_full_handler()
    client = _make_client(handler)

    monkeypatch.setattr(cli_module, "yesterday_in_toronto", lambda: _TARGET_DATE)

    def factory(_args: object) -> tuple[DailyLoader, Callable[[], None]]:
        return _build_daily_loader(client, storage), client.close

    exit_code = cli_module.main(
        [
            "daily",
            "--ingest-date",
            _INGEST_DATE.isoformat(),
            "--log-level",
            "WARNING",
        ],
        daily_loader_factory=factory,
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["target_date"] == _TARGET_DATE.isoformat()


# --------------------------------------------------------------------
# Manifest interaction sanity — using the default key
# --------------------------------------------------------------------


def test_daily_loader_writes_manifest_at_default_key(tmp_path: Path) -> None:
    """Sanity: the manifest object lands at the documented key."""
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_full_handler()
    with _make_client(handler) as client:
        loader = _build_daily_loader(client, storage)
        loader.load_date(_TARGET_DATE, ingest_date=_INGEST_DATE)

    keys = list(storage.list_objects(DEFAULT_MANIFEST_KEY))
    assert keys == [DEFAULT_MANIFEST_KEY]
