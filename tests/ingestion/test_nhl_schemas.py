"""Tests for ``puckbunny.ingestion.nhl.schemas``.

We validate the per-endpoint pydantic models against the recorded
fixtures from the PR-A spike (a real ``api-web.nhle.com`` payload),
plus a handful of synthetic edge cases to exercise the spike-§7
game-id-vs-season invariant.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from puckbunny.ingestion.nhl.schemas import (
    BoxscoreResponse,
    LandingResponse,
    PlayByPlayResponse,
    TeamRef,
    assert_game_id_matches_season,
)

_FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "games"
_LANDING_FIXTURE: Path = _FIXTURES_DIR / "landing_2025030123.json"
_BOXSCORE_FIXTURE: Path = _FIXTURES_DIR / "boxscore_2025030123.json"
_PBP_FIXTURE: Path = _FIXTURES_DIR / "play_by_play_2025030123.json"


def _load_landing() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_LANDING_FIXTURE.read_text(encoding="utf-8"))
    return data


def _load_boxscore() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_BOXSCORE_FIXTURE.read_text(encoding="utf-8"))
    return data


def _load_pbp() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_PBP_FIXTURE.read_text(encoding="utf-8"))
    return data


# --------------------------------------------------------------------
# LandingResponse
# --------------------------------------------------------------------


def test_landing_parses_real_fixture() -> None:
    payload = _load_landing()
    landing = LandingResponse.model_validate(payload)

    # Spike notes §6: ``id`` is the canonical natural-key field.
    assert landing.id == 2025030123
    assert landing.season == 20252026
    assert landing.gameType == 3
    assert landing.gameDate.isoformat() == "2026-04-24"
    assert landing.gameState == "OFF"
    # Datetime is timezone-aware (Z suffix in source).
    assert landing.startTimeUTC.tzinfo is not None
    # Team refs.
    assert isinstance(landing.awayTeam, TeamRef)
    assert landing.awayTeam.id == 14
    assert landing.awayTeam.abbrev == "TBL"
    assert landing.homeTeam.id == 8
    assert landing.homeTeam.abbrev == "MTL"


def test_landing_preserves_unknown_top_level_fields() -> None:
    """``extra="allow"`` so future API additions don't break parsing."""
    payload = _load_landing()
    payload["someBrandNewKey"] = {"foo": "bar"}
    landing = LandingResponse.model_validate(payload)
    assert landing.model_extra is not None
    assert landing.model_extra.get("someBrandNewKey") == {"foo": "bar"}


def test_landing_rejects_missing_required_field() -> None:
    payload = _load_landing()
    del payload["gameDate"]
    with pytest.raises(ValidationError) as exc_info:
        LandingResponse.model_validate(payload)
    assert "gameDate" in str(exc_info.value)


# --------------------------------------------------------------------
# BoxscoreResponse
# --------------------------------------------------------------------


def test_boxscore_parses_real_fixture() -> None:
    payload = _load_boxscore()
    boxscore = BoxscoreResponse.model_validate(payload)
    assert boxscore.id == 2025030123
    # Boxscore-only required fields.
    assert "awayTeam" in boxscore.playerByGameStats
    assert "homeTeam" in boxscore.playerByGameStats
    assert set(boxscore.playerByGameStats["awayTeam"].keys()) >= {
        "forwards",
        "defense",
        "goalies",
    }
    assert "lastPeriodType" in boxscore.gameOutcome


def test_boxscore_requires_player_by_game_stats() -> None:
    payload = _load_boxscore()
    del payload["playerByGameStats"]
    with pytest.raises(ValidationError) as exc_info:
        BoxscoreResponse.model_validate(payload)
    assert "playerByGameStats" in str(exc_info.value)


def test_boxscore_requires_game_outcome() -> None:
    payload = _load_boxscore()
    del payload["gameOutcome"]
    with pytest.raises(ValidationError) as exc_info:
        BoxscoreResponse.model_validate(payload)
    assert "gameOutcome" in str(exc_info.value)


# --------------------------------------------------------------------
# PlayByPlayResponse
# --------------------------------------------------------------------


def test_pbp_parses_real_fixture() -> None:
    payload = _load_pbp()
    parsed = PlayByPlayResponse.model_validate(payload)
    assert parsed.id == 2025030123
    # Spike key-scan numbers — 319 plays, 40 rosterSpots.
    assert len(parsed.plays) == 319
    assert len(parsed.rosterSpots) == 40


def test_pbp_rejects_game_id_season_mismatch() -> None:
    payload = _load_pbp()
    payload["season"] = 20242025
    with pytest.raises(ValidationError, match="game-id format violation"):
        PlayByPlayResponse.model_validate(payload)


# --------------------------------------------------------------------
# Spike §7: game-id-vs-season invariant
# --------------------------------------------------------------------


def test_landing_rejects_game_id_season_mismatch() -> None:
    """`id // 1_000_000` must equal `int(str(season)[:4])`."""
    payload = _load_landing()
    # Same id, but season claims 2024 — a 1-year drift would trip
    # silent corruption later.
    payload["season"] = 20242025
    with pytest.raises(ValidationError, match="game-id format violation"):
        LandingResponse.model_validate(payload)


def test_boxscore_rejects_game_id_season_mismatch() -> None:
    payload = _load_boxscore()
    payload["season"] = 20242025
    with pytest.raises(ValidationError, match="game-id format violation"):
        BoxscoreResponse.model_validate(payload)


def test_assert_game_id_matches_season_passes_for_valid() -> None:
    # 2025030123 → year 2025 → season 20252026.
    assert_game_id_matches_season(2025030123, 20252026)
    # Accepts season as a string too — the schedule loader (PR-E)
    # may have it pre-stringified.
    assert_game_id_matches_season(2025030123, "20252026")


def test_assert_game_id_matches_season_raises_for_drift() -> None:
    with pytest.raises(ValueError, match="game-id format violation"):
        assert_game_id_matches_season(2025030123, 20242025)


# --------------------------------------------------------------------
# TeamRef
# --------------------------------------------------------------------


def test_team_ref_requires_id_and_abbrev() -> None:
    with pytest.raises(ValidationError):
        TeamRef.model_validate({"id": 14})  # missing abbrev
    with pytest.raises(ValidationError):
        TeamRef.model_validate({"abbrev": "TBL"})  # missing id


def test_team_ref_preserves_extras() -> None:
    ref = TeamRef.model_validate(
        {"id": 14, "abbrev": "TBL", "score": 2, "logo": "https://example/x.svg"}
    )
    assert ref.model_extra is not None
    assert ref.model_extra.get("score") == 2
    assert ref.model_extra.get("logo") == "https://example/x.svg"
