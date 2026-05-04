"""Tests for ``puckbunny.ingestion.nhl.season_summaries`` and the
``season-summaries`` CLI.

Same cassette pattern as :mod:`tests.ingestion.test_nhl_games`:
:class:`httpx.MockTransport` serves committed JSON fixtures from
``tests/ingestion/fixtures/season_summaries/``. The stats-rest surface
takes query parameters (``cayenneExp``, ``limit``) so request matching
is on URL ``path`` rather than the full URL — query-string equality
would couple tests to the loader's exact param-dict ordering, which
isn't a contract worth pinning.

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
    GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
    SKATER_SUMMARY_ENDPOINT_TEMPLATE,
    TEAM_SUMMARY_ENDPOINT_TEMPLATE,
    season_start_date,
    season_summary_query_params,
)
from puckbunny.ingestion.nhl.season_summaries import (
    GOALIE_SUMMARY_PARTITION_NAME,
    SKATER_SUMMARY_PARTITION_NAME,
    TEAM_SUMMARY_PARTITION_NAME,
    SeasonSummariesLoader,
)
from puckbunny.storage.local import LocalFilesystemStorage
from puckbunny.storage.parquet import ENVELOPE_SCHEMA

if TYPE_CHECKING:
    from collections.abc import Callable

_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "season_summaries"
_SKATER_FIXTURE: Path = _FIXTURES_DIR / "skater_summary_20242025.json"
_GOALIE_FIXTURE: Path = _FIXTURES_DIR / "goalie_summary_20242025.json"
_TEAM_FIXTURE: Path = _FIXTURES_DIR / "team_summary_20242025.json"
_SEASON: str = "20242025"

_SKATER_PATH: str = "/stats/rest/en/skater/summary"
_GOALIE_PATH: str = "/stats/rest/en/goalie/summary"
_TEAM_PATH: str = "/stats/rest/en/team/summary"


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _read_fixture(path: Path) -> bytes:
    """Read the fixture as bytes — preserves exact byte sequence so
    ``response_sha256`` is deterministic across runs."""
    return path.read_bytes()


def _make_handler(
    *,
    skater_body: bytes | None = None,
    goalie_body: bytes | None = None,
    team_body: bytes | None = None,
    skater_status: int = 200,
    goalie_status: int = 200,
    team_status: int = 200,
    on_request: Callable[[httpx.Request], None] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a ``MockTransport`` handler that maps the canonical NHL
    stats-rest paths to fixture bodies. Each call records the inbound
    request via ``on_request`` (when supplied) so tests can assert
    headers, query params, etc.

    URL matching is on path only — query params (``cayenneExp``,
    ``limit``) are exercised in dedicated tests rather than embedded
    in the routing key.
    """
    skater_body = skater_body if skater_body is not None else _read_fixture(_SKATER_FIXTURE)
    goalie_body = goalie_body if goalie_body is not None else _read_fixture(_GOALIE_FIXTURE)
    team_body = team_body if team_body is not None else _read_fixture(_TEAM_FIXTURE)

    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        path = request.url.path
        if path == _SKATER_PATH:
            return httpx.Response(
                skater_status,
                content=skater_body,
                headers={"content-type": "application/json"},
            )
        if path == _GOALIE_PATH:
            return httpx.Response(
                goalie_status,
                content=goalie_body,
                headers={"content-type": "application/json"},
            )
        if path == _TEAM_PATH:
            return httpx.Response(
                team_status,
                content=team_body,
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, json={"error": "unmapped path", "path": path})

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
# SeasonSummariesLoader.load_one
# --------------------------------------------------------------------


def test_load_one_writes_three_endpoints_to_separate_partitions(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_handler(on_request=requests_seen.append)

    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        result = loader.load_one(_SEASON, ingest_date=date(2026, 4, 28))

    assert result.season == _SEASON
    # Each endpoint goes to its own bronze partition.
    assert (
        f"/nhl_api/{SKATER_SUMMARY_PARTITION_NAME}/ingest_date=2026-04-28/"
        in result.skater_summary.key
    )
    assert (
        f"/nhl_api/{GOALIE_SUMMARY_PARTITION_NAME}/ingest_date=2026-04-28/"
        in result.goalie_summary.key
    )
    assert (
        f"/nhl_api/{TEAM_SUMMARY_PARTITION_NAME}/ingest_date=2026-04-28/" in result.team_summary.key
    )
    # One bronze row per fetch (per-fetch granularity, see the loader
    # docstring's "Bronze row granularity" section).
    assert result.skater_summary.rows == 1
    assert result.goalie_summary.rows == 1
    assert result.team_summary.rows == 1
    # All three endpoints were called, in skater/goalie/team order.
    assert [r.url.path for r in requests_seen] == [
        _SKATER_PATH,
        _GOALIE_PATH,
        _TEAM_PATH,
    ]


def test_load_one_envelope_columns_match_response(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()

    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        result = loader.load_one(_SEASON, ingest_date=date(2026, 4, 28))

    skater_table = _read_envelope_table(storage, result.skater_summary.key)
    assert skater_table.schema.equals(ENVELOPE_SCHEMA)
    # Per the design doc: entity_id is str(seasonId) for season-scoped
    # endpoints — the natural-key column is "weakly" populated and the
    # row represents a season-bag-of-skaters, not an individual entity.
    assert skater_table.column("entity_id").to_pylist() == [_SEASON]
    assert skater_table.column("season").to_pylist() == [_SEASON]
    # event_date is the Oct-1 sentinel from season_start_date(season).
    assert skater_table.column("event_date").to_pylist() == [date(2024, 10, 1)]
    assert skater_table.column("endpoint").to_pylist() == [SKATER_SUMMARY_ENDPOINT_TEMPLATE]
    # response_json holds the verbatim API body — the {data, total}
    # envelope, not just the data array. Same verbatim guarantee as
    # PR-C/D.
    rj = skater_table.column("response_json").to_pylist()[0]
    assert rj == _SKATER_FIXTURE.read_text(encoding="utf-8")
    parsed = json.loads(rj)
    assert parsed["total"] == 2
    assert len(parsed["data"]) == 2
    # endpoint_params_json captures the wire-truth dict.
    params = json.loads(skater_table.column("endpoint_params_json").to_pylist()[0])
    assert params == {"cayenneExp": f"seasonId={_SEASON}", "limit": -1}

    # Spot-check the other two endpoints landed at their correct
    # endpoint templates — full column equality is exercised via the
    # skater table; this just guards against a copy-paste bug.
    goalie_table = _read_envelope_table(storage, result.goalie_summary.key)
    assert goalie_table.column("endpoint").to_pylist() == [GOALIE_SUMMARY_ENDPOINT_TEMPLATE]
    assert goalie_table.column("entity_id").to_pylist() == [_SEASON]

    team_table = _read_envelope_table(storage, result.team_summary.key)
    assert team_table.column("endpoint").to_pylist() == [TEAM_SUMMARY_ENDPOINT_TEMPLATE]
    assert team_table.column("entity_id").to_pylist() == [_SEASON]


def test_load_one_sends_expected_query_params(tmp_path: Path) -> None:
    """Each request carries ``cayenneExp=seasonId=...`` and
    ``limit=-1`` — defensive against a regression that drops either
    parameter, since the spike notes confirmed both are load-bearing
    (default ``limit`` caps at 50; missing ``cayenneExp`` returns
    everything across all seasons).
    """
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_handler(on_request=requests_seen.append)

    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        loader.load_one(_SEASON, ingest_date=date(2026, 4, 28))

    expected_params = season_summary_query_params(_SEASON)
    for request in requests_seen:
        assert request.url.params.get("cayenneExp") == expected_params["cayenneExp"]
        assert request.url.params.get("limit") == str(expected_params["limit"])


def test_load_one_uses_today_when_ingest_date_omitted(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        result = loader.load_one(_SEASON)
    # Just check it landed in *some* ingest_date partition; we don't
    # assert the exact value to avoid a midnight-UTC flake.
    assert "/ingest_date=" in result.skater_summary.key
    assert "/ingest_date=" in result.goalie_summary.key
    assert "/ingest_date=" in result.team_summary.key


def test_load_one_accepts_int_season(tmp_path: Path) -> None:
    """Loader normalizes int seasons to str — both forms are valid."""
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()

    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        result = loader.load_one(20242025, ingest_date=date(2026, 4, 28))

    assert result.season == _SEASON


def test_load_one_event_date_uses_season_start_sentinel(tmp_path: Path) -> None:
    """Confirm the Oct-1-of-start-year sentinel against the standalone
    helper — guards against the loader and helper drifting out of sync.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()

    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        result = loader.load_one(_SEASON, ingest_date=date(2026, 4, 28))

    expected = season_start_date(_SEASON)
    assert expected == date(2024, 10, 1)
    skater_table = _read_envelope_table(storage, result.skater_summary.key)
    goalie_table = _read_envelope_table(storage, result.goalie_summary.key)
    team_table = _read_envelope_table(storage, result.team_summary.key)
    assert skater_table.column("event_date").to_pylist() == [expected]
    assert goalie_table.column("event_date").to_pylist() == [expected]
    assert team_table.column("event_date").to_pylist() == [expected]


def test_load_one_raises_when_total_disagrees_with_data_len(tmp_path: Path) -> None:
    """The ``len(data) == total`` envelope invariant must fail loud
    via the schema's post-validator. Bronze must not receive a row
    derived from a truncated payload.
    """
    storage = LocalFilesystemStorage(tmp_path)
    # Swap total to a value that disagrees with len(data)=2.
    rewritten = json.loads(_SKATER_FIXTURE.read_text(encoding="utf-8"))
    rewritten["total"] = 999
    handler = _make_handler(skater_body=json.dumps(rewritten).encode("utf-8"))

    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        with pytest.raises(ValidationError, match="envelope contract violation"):
            loader.load_one(_SEASON, ingest_date=date(2026, 4, 28))

    # Nothing should have been written to any season-summary partition
    # since we failed during the first endpoint (skater).
    assert list(storage.list_objects(f"bronze/nhl_api/{SKATER_SUMMARY_PARTITION_NAME}")) == []
    assert list(storage.list_objects(f"bronze/nhl_api/{GOALIE_SUMMARY_PARTITION_NAME}")) == []
    assert list(storage.list_objects(f"bronze/nhl_api/{TEAM_SUMMARY_PARTITION_NAME}")) == []


def test_load_one_propagates_validation_error(tmp_path: Path) -> None:
    """A malformed response (missing ``data`` / ``total``) should
    surface as ``ValidationError``, not silently land a bad row.
    """
    storage = LocalFilesystemStorage(tmp_path)
    bad_body = json.dumps({"unexpected": "shape"}).encode("utf-8")
    handler = _make_handler(skater_body=bad_body)

    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        with pytest.raises(ValidationError):
            loader.load_one(_SEASON, ingest_date=date(2026, 4, 28))


def test_load_one_rejects_malformed_season(tmp_path: Path) -> None:
    """Season identifier must be 8 digits; non-conforming values raise
    before any I/O.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()

    with _make_client(handler) as client:
        loader = SeasonSummariesLoader(client, storage)
        with pytest.raises(ValueError, match="8 digits"):
            loader.load_one("2024-25", ingest_date=date(2026, 4, 28))


# --------------------------------------------------------------------
# CLI: python -m puckbunny.ingestion.nhl season-summaries --season ...
# --------------------------------------------------------------------


def test_cli_season_summaries_subcommand_end_to_end(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main(["season-summaries", "--season", ...])`` runs through the
    full fetch+write path with mocked transport and prints a JSON
    summary.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    client = _make_client(handler)

    def factory(_args: object) -> tuple[SeasonSummariesLoader, Callable[[], None]]:
        return SeasonSummariesLoader(client, storage), client.close

    exit_code = cli_module.main(
        [
            "season-summaries",
            "--season",
            _SEASON,
            "--ingest-date",
            "2026-04-28",
            "--log-level",
            "WARNING",
        ],
        season_summaries_loader_factory=factory,
    )
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    summary = json.loads(out)
    assert summary["season"] == _SEASON
    assert SKATER_SUMMARY_PARTITION_NAME in summary["skater_summary"]["key"]
    assert GOALIE_SUMMARY_PARTITION_NAME in summary["goalie_summary"]["key"]
    assert TEAM_SUMMARY_PARTITION_NAME in summary["team_summary"]["key"]
    assert summary["skater_summary"]["rows"] == 1
    assert summary["goalie_summary"]["rows"] == 1
    assert summary["team_summary"]["rows"] == 1


def test_cli_rejects_missing_season(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--season`` is required; argparse should error before any I/O."""
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main(["season-summaries"])
    # argparse exits with code 2 on usage errors.
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--season" in err
