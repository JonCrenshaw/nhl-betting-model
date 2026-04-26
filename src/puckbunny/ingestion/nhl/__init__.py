"""NHL bronze ingestion — game-level, season-level, and discovery loaders.

PR-C delivers the game-level landing + boxscore endpoints and the CLI
shell. Subsequent PRs add play-by-play (PR-D), schedule + daily walker
(PR-E), season-scoped loaders (PR-F), and the backfill manifest (PR-G).
See ``docs/milestones/m2-nhl-ingestion.md`` for the work breakdown.
"""

from __future__ import annotations

from puckbunny.ingestion.nhl.endpoints import (
    BOXSCORE_ENDPOINT_TEMPLATE,
    LANDING_ENDPOINT_TEMPLATE,
    NHL_API_BASE_URL,
    boxscore_url,
    landing_url,
)
from puckbunny.ingestion.nhl.games import GameIdMismatchError, GameLoader, GameLoadResult
from puckbunny.ingestion.nhl.schemas import (
    BoxscoreResponse,
    GameResponseBase,
    LandingResponse,
    TeamRef,
    assert_game_id_matches_season,
)

__all__ = [
    "BOXSCORE_ENDPOINT_TEMPLATE",
    "LANDING_ENDPOINT_TEMPLATE",
    "NHL_API_BASE_URL",
    "BoxscoreResponse",
    "GameIdMismatchError",
    "GameLoadResult",
    "GameLoader",
    "GameResponseBase",
    "LandingResponse",
    "TeamRef",
    "assert_game_id_matches_season",
    "boxscore_url",
    "landing_url",
]
