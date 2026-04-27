"""Tests for ``puckbunny.ingestion.nhl.play_by_play`` and the
``play-by-play`` CLI subcommand.

Same cassette pattern as ``test_nhl_games.py`` — ``httpx.MockTransport``
serves the recorded fixture from the PR-A spike, and the storage target
is :class:`puckbunny.storage.local.LocalFilesystemStorage` under
``tmp_path``. We don't use ``pytest-recording`` for the same reasons
spelled out in the games tests: we already have the JSON committed and
we want fine-grained URL → fixture mapping.
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
from puckbunny.ingestion.nhl.endpoints import play_by_play_url
from puckbunny.ingestion.nhl.play_by_play import (
    GameIdMismatchError,
    PlayByPlayLoader,
)
from puckbunny.ingestion.nhl.schemas import PlayByPlayResponse
from puckbunny.storage.local import LocalFilesystemStorage
from puckbunny.storage.parquet import ENVELOPE_SCHEMA

if TYPE_CHECKING:
    from collections.abc import Callable

_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "games"
_PBP_FIXTURE: Path = _FIXTURES_DIR / "play_by_play_2025030123.json"
_GAME_ID: int = 2025030123


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _read_fixture(path: Path) -> bytes:
    """Read the fixture as bytes — preserves the exact byte sequence so
    ``response_sha256`` is deterministic across runs."""
    return path.read_bytes()


def _make_handler(
    *,
    body: bytes | None = None,
    status: int = 200,
    on_request: Callable[[httpx.Request], None] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Map ``play_by_play_url(_GAME_ID)`` to the fixture body."""
    body = body if body is not None else _read_fixture(_PBP_FIXTURE)
    target = play_by_play_url(_GAME_ID)

    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        url = str(request.url)
        if url == target:
            return httpx.Response(
                status,
                content=body,
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
# PlayByPlayResponse schema (sanity — full coverage in test_nhl_schemas)
# --------------------------------------------------------------------


def test_pbp_response_parses_real_fixture() -> None:
    """The schema must parse the recorded payload without flinching, and
    the two pinned collections (``plays``/``rosterSpots``) must be
    populated."""
    payload = json.loads(_PBP_FIXTURE.read_text(encoding="utf-8"))
    parsed = PlayByPlayResponse.model_validate(payload)

    assert parsed.id == _GAME_ID
    assert parsed.season == 20252026
    assert parsed.gameDate.isoformat() == "2026-04-24"
    # Spike key-scan numbers — 319 plays, 40 rosterSpots.
    assert len(parsed.plays) == 319
    assert len(parsed.rosterSpots) == 40


def test_pbp_response_requires_plays() -> None:
    payload = json.loads(_PBP_FIXTURE.read_text(encoding="utf-8"))
    del payload["plays"]
    with pytest.raises(ValidationError) as exc_info:
        PlayByPlayResponse.model_validate(payload)
    assert "plays" in str(exc_info.value)


def test_pbp_response_requires_roster_spots() -> None:
    payload = json.loads(_PBP_FIXTURE.read_text(encoding="utf-8"))
    del payload["rosterSpots"]
    with pytest.raises(ValidationError) as exc_info:
        PlayByPlayResponse.model_validate(payload)
    assert "rosterSpots" in str(exc_info.value)


# --------------------------------------------------------------------
# PlayByPlayLoader.load_one
# --------------------------------------------------------------------


def test_load_one_writes_to_play_by_play_partition(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    requests_seen: list[httpx.Request] = []
    handler = _make_handler(on_request=requests_seen.append)

    with _make_client(handler) as client:
        loader = PlayByPlayLoader(client, storage)
        result = loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    assert result.game_id == _GAME_ID
    # Play-by-play has its own bronze partition. Hyphen, not underscore —
    # matches the URL slug.
    assert "/nhl_api/play-by-play/ingest_date=2026-04-25/" in result.play_by_play.key
    assert result.play_by_play.rows == 1
    # One HTTP call only — PxP is the single-endpoint loader.
    assert [str(r.url) for r in requests_seen] == [play_by_play_url(_GAME_ID)]


def test_load_one_envelope_columns_match_response(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()

    with _make_client(handler) as client:
        loader = PlayByPlayLoader(client, storage)
        result = loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    table = _read_envelope_table(storage, result.play_by_play.key)
    assert table.schema.equals(ENVELOPE_SCHEMA)
    assert table.column("entity_id").to_pylist() == ["2025030123"]
    assert table.column("season").to_pylist() == ["20252026"]
    assert table.column("event_date").to_pylist() == [date(2026, 4, 24)]
    assert table.column("endpoint").to_pylist() == ["/v1/gamecenter/{gameId}/play-by-play"]
    # The verbatim API body is preserved — this is the bronze contract.
    rj = table.column("response_json").to_pylist()[0]
    assert rj == _PBP_FIXTURE.read_text(encoding="utf-8")
    # And the parameters dict captures the substituted gameId.
    params = json.loads(table.column("endpoint_params_json").to_pylist()[0])
    assert params == {"gameId": _GAME_ID}


def test_load_one_uses_today_when_ingest_date_omitted(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    with _make_client(handler) as client:
        loader = PlayByPlayLoader(client, storage)
        result = loader.load_one(_GAME_ID)
    assert "/ingest_date=" in result.play_by_play.key


def test_load_one_sends_user_agent(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    captured: dict[str, str] = {}

    def grab_ua(request: httpx.Request) -> None:
        captured.setdefault("ua", request.headers.get("user-agent", ""))

    handler = _make_handler(on_request=grab_ua)
    with _make_client(handler) as client:
        loader = PlayByPlayLoader(client, storage)
        loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    assert captured["ua"]


def test_load_one_raises_on_game_id_mismatch(tmp_path: Path) -> None:
    """If the response's ``id`` differs from the requested game_id, fail loud."""
    storage = LocalFilesystemStorage(tmp_path)
    rewritten = json.loads(_PBP_FIXTURE.read_text(encoding="utf-8"))
    # Spike-§7 invariant means we have to bump both id and season for
    # the response to validate up to the id-mismatch check.
    rewritten["id"] = 2025030124
    handler = _make_handler(body=json.dumps(rewritten).encode("utf-8"))

    with _make_client(handler) as client:
        loader = PlayByPlayLoader(client, storage)
        with pytest.raises(GameIdMismatchError, match="2025030124"):
            loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    # Nothing should have been written.
    assert list(storage.list_objects("bronze/nhl_api/play-by-play")) == []


def test_load_one_propagates_validation_error(tmp_path: Path) -> None:
    """A response missing the pinned ``plays`` field must raise
    ``ValidationError``, not write a half-shaped envelope."""
    storage = LocalFilesystemStorage(tmp_path)
    bad = json.loads(_PBP_FIXTURE.read_text(encoding="utf-8"))
    del bad["plays"]
    handler = _make_handler(body=json.dumps(bad).encode("utf-8"))

    with _make_client(handler) as client:
        loader = PlayByPlayLoader(client, storage)
        with pytest.raises(ValidationError):
            loader.load_one(_GAME_ID, ingest_date=date(2026, 4, 25))

    assert list(storage.list_objects("bronze/nhl_api/play-by-play")) == []


# --------------------------------------------------------------------
# CLI: python -m puckbunny.ingestion.nhl play-by-play --game-id ...
# --------------------------------------------------------------------


def test_cli_play_by_play_subcommand_end_to_end(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main(["play-by-play", "--game-id", ...])`` runs the full
    fetch+write path with mocked transport and prints a JSON summary.
    """
    storage = LocalFilesystemStorage(tmp_path)
    handler = _make_handler()
    client = _make_client(handler)

    def factory(_args: object) -> tuple[PlayByPlayLoader, Callable[[], None]]:
        return PlayByPlayLoader(client, storage), client.close

    exit_code = cli_module.main(
        [
            "play-by-play",
            "--game-id",
            str(_GAME_ID),
            "--ingest-date",
            "2026-04-25",
            "--log-level",
            "WARNING",
        ],
        pbp_loader_factory=factory,
    )
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    summary = json.loads(out)
    assert summary["game_id"] == _GAME_ID
    assert "play-by-play" in summary["play_by_play"]["key"]
    assert summary["play_by_play"]["rows"] == 1
    assert summary["play_by_play"]["bytes"] > 0


def test_cli_play_by_play_rejects_missing_game_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--game-id`` is required; argparse should error before any I/O."""
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main(["play-by-play"])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--game-id" in err
