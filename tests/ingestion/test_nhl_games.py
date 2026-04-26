"""Tests for ``puckbunny.ingestion.nhl.games`` and the ``games`` CLI.

We use ``httpx.MockTransport`` to serve the recorded fixtures from the
PR-A spike. This is the test pattern the M2 plan calls "cassette tests"
— pre-recorded responses replayed deterministically with no network.
``pytest-recording`` is the plan's preferred wire-up; here we use the
lower-level ``MockTransport`` directly because (a) the response shapes
are already saved as JSON in ``tests/ingestion/fixtures/games/`` and
(b) we want fine-grained control over which URL maps to which fixture
to assert the loader hits the right endpoints.

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
from puckbunny.ingestion.nhl.endpoints import boxscore_url, landing_url
from puckbunny.ingestion.nhl.games import GameIdMismatchError, GameLoader
from puckbunny.storage.local import LocalFilesystemStorage
from puckbunny.storage.parquet import ENVELOPE_SCHEMA

if TYPE_CHECKING:
    from collections.abc import Callable

_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "games"
_LANDING_FIXTURE: Path = _FIXTURES_DIR / "landing_2025030123.json"
_BOXSCORE_FIXTURE: Path = _FIXTURES_DIR / "boxscore_2025030123.json"
_GAME_ID: int = 2025030123


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _read_fixture(path: Path) -> bytes:
    """Read the fixture as bytes — preserves exact byte sequence so
    ``response_sha256`` is deterministic across runs."""
    return path.read_bytes()


def _make_handler(
    *,
    landing_body: bytes | None = None,
    boxscore_body: bytes | None = None,
    landing_status: int = 200,
    boxscore_status: int = 200,
    on_request: Callable[[httpx.Request], None] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a ``MockTransport`` handler that maps the canonical NHL
    URLs to fixture bodies. Each call records the inbound request via
    ``on_request`` (when supplied) so tests can assert headers etc.
    """
    landing_body = landing_body if landing_body is not None else _read_fixture(_LANDING_FIXTURE)
    boxscore_body = boxscore_body if boxscore_body is not None else _read_fixture(_BOXSCORE_FIXTURE)

    landing_target = landing_url(_GAME_ID)
    boxscore_target = boxscore_url(_GAME_ID)

    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        url = str(request.url)
        if url == landing_target:
            return httpx.Response(
                landing_status,
                content=landing_body,
                headers={"content-type": "application/json"},
            )
        if url == boxscore_target:
            return httpx.Response(
                boxscore_status,
                content=boxscore_body,
                headers={"content-type": "application/json"},
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
# GameLoader.load_one
# --------------------------------------------------------------------


def test_load_one_writes_both_endpoints_to_separate_partitions(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_handler(on_request=requests_seen.append)

    with _make_client(handler) as client:
        loader = GameLoader(client, storage)
        result = loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    assert result.game_id == _GAME_ID
    # Each endpoint goes to its own bronze partition.
    assert "/nhl_api/landing/ingest_date=2026-04-25/" in result.landing.key
    assert "/nhl_api/boxscore/ingest_date=2026-04-25/" in result.boxscore.key
    assert result.landing.rows == 1
    assert result.boxscore.rows == 1
    # Both endpoints were called, in order.
    assert [str(r.url) for r in requests_seen] == [
        landing_url(_GAME_ID),
        boxscore_url(_GAME_ID),
    ]


def test_load_one_envelope_columns_match_response(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()

    with _make_client(handler) as client:
        loader = GameLoader(client, storage)
        result = loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    landing_table = _read_envelope_table(storage, result.landing.key)
    assert landing_table.schema.equals(ENVELOPE_SCHEMA)
    assert landing_table.column("entity_id").to_pylist() == ["2025030123"]
    assert landing_table.column("season").to_pylist() == ["20252026"]
    assert landing_table.column("event_date").to_pylist() == [date(2026, 4, 24)]
    assert landing_table.column("endpoint").to_pylist() == ["/v1/gamecenter/{gameId}/landing"]
    # response_json column holds the verbatim API body (including the
    # raw ``{"id": 2025030123, ...}`` start). We didn't re-serialize.
    rj = landing_table.column("response_json").to_pylist()[0]
    assert json.loads(rj)["id"] == _GAME_ID
    assert rj == _LANDING_FIXTURE.read_text(encoding="utf-8")
    # endpoint_params_json captures the substituted gameId.
    params = json.loads(landing_table.column("endpoint_params_json").to_pylist()[0])
    assert params == {"gameId": _GAME_ID}

    boxscore_table = _read_envelope_table(storage, result.boxscore.key)
    assert boxscore_table.column("endpoint").to_pylist() == ["/v1/gamecenter/{gameId}/boxscore"]


def test_load_one_uses_today_when_ingest_date_omitted(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    with _make_client(handler) as client:
        loader = GameLoader(client, storage)
        result = loader.load_one(_GAME_ID)
    # Just check it landed in *some* ingest_date partition; we don't
    # assert the exact value to avoid a midnight-UTC flake.
    assert "/ingest_date=" in result.landing.key
    assert "/ingest_date=" in result.boxscore.key


def test_load_one_sends_user_agent(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    captured: dict[str, str] = {}

    def grab_ua(request: httpx.Request) -> None:
        captured.setdefault("ua", request.headers.get("user-agent", ""))

    handler = _make_handler(on_request=grab_ua)
    with _make_client(handler) as client:
        loader = GameLoader(client, storage)
        loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    # Whatever UA the test client uses, it must be set — defensive
    # against a regression that drops the header.
    assert captured["ua"]


def test_load_one_raises_on_game_id_mismatch(tmp_path: Path) -> None:
    """If the response's ``id`` differs from the requested game_id, fail loud."""
    storage = LocalFilesystemStorage(tmp_path)
    # Wrong id in the landing body, but it still has to be consistent
    # with its season per the spike-§7 invariant — so swap both.
    rewritten = json.loads(_LANDING_FIXTURE.read_text(encoding="utf-8"))
    rewritten["id"] = 2025030124
    handler = _make_handler(landing_body=json.dumps(rewritten).encode("utf-8"))

    with _make_client(handler) as client:
        loader = GameLoader(client, storage)
        with pytest.raises(GameIdMismatchError, match="2025030124"):
            loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    # Nothing should have been written to the boxscore partition since
    # we failed during landing.
    assert list(storage.list_objects("bronze/nhl_api/boxscore")) == []


def test_load_one_propagates_validation_error(tmp_path: Path) -> None:
    """A malformed response should surface as ``ValidationError``, not
    silently skip the row."""
    storage = LocalFilesystemStorage(tmp_path)
    bad_body = json.dumps({"id": _GAME_ID, "season": 20252026}).encode("utf-8")
    handler = _make_handler(landing_body=bad_body)

    with _make_client(handler) as client:
        loader = GameLoader(client, storage)
        with pytest.raises(ValidationError):
            loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))


# --------------------------------------------------------------------
# CLI: python -m puckbunny.ingestion.nhl games --game-id ...
# --------------------------------------------------------------------


def test_cli_games_subcommand_end_to_end(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main(["games", "--game-id", ...])`` runs through the full
    fetch+write path with mocked transport and prints a JSON summary.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    client = _make_client(handler)

    def factory(_args: object) -> tuple[GameLoader, Callable[[], None]]:
        return GameLoader(client, storage), client.close

    exit_code = cli_module.main(
        [
            "games",
            "--game-id",
            str(_GAME_ID),
            "--ingest-date",
            "2026-04-25",
            "--log-level",
            "WARNING",
        ],
        loader_factory=factory,
    )
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    summary = json.loads(out)
    assert summary["game_id"] == _GAME_ID
    assert "landing" in summary["landing"]["key"]
    assert "boxscore" in summary["boxscore"]["key"]
    assert summary["landing"]["rows"] == 1
    assert summary["boxscore"]["rows"] == 1


def test_cli_rejects_missing_game_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--game-id`` is required; argparse should error before any I/O."""
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main(["games"])
    # argparse exits with code 2 on usage errors.
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--game-id" in err


def test_cli_rejects_missing_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main([])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "command" in err.lower() or "required" in err.lower()
