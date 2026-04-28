"""NHL bronze ingestion — game-level, season-level, and discovery loaders.

PR-C delivers the game-level landing + boxscore endpoints and the CLI
shell. PR-D added play-by-play. PR-E adds the schedule fetcher + daily
walker that orchestrates the per-game loaders with manifest-based
dedupe. Subsequent PRs add season-scoped loaders (PR-F) and the
backfill CLI (PR-G). See ``docs/milestones/m2-nhl-ingestion.md`` for
the work breakdown.
"""

from __future__ import annotations

from puckbunny.ingestion.nhl.endpoints import (
    BOXSCORE_ENDPOINT_TEMPLATE,
    INGESTIBLE_GAME_STATES,
    LANDING_ENDPOINT_TEMPLATE,
    NHL_API_BASE_URL,
    PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
    SCHEDULE_ENDPOINT_TEMPLATE,
    boxscore_url,
    landing_url,
    play_by_play_url,
    schedule_url,
)
from puckbunny.ingestion.nhl.games import GameIdMismatchError, GameLoader, GameLoadResult
from puckbunny.ingestion.nhl.play_by_play import (
    PlayByPlayLoader,
    PlayByPlayLoadResult,
)
from puckbunny.ingestion.nhl.schedule import (
    DailyLoader,
    DailyLoadResult,
    GameOutcome,
    ScheduleDayNotFoundError,
    ScheduleLoader,
    filter_ingestible,
    select_day,
    yesterday_in_toronto,
)
from puckbunny.ingestion.nhl.schemas import (
    BoxscoreResponse,
    GameResponseBase,
    LandingResponse,
    PlayByPlayResponse,
    ScheduleDay,
    ScheduleGame,
    ScheduleResponse,
    TeamRef,
    assert_game_id_matches_season,
)

__all__ = [
    "BOXSCORE_ENDPOINT_TEMPLATE",
    "INGESTIBLE_GAME_STATES",
    "LANDING_ENDPOINT_TEMPLATE",
    "NHL_API_BASE_URL",
    "PLAY_BY_PLAY_ENDPOINT_TEMPLATE",
    "SCHEDULE_ENDPOINT_TEMPLATE",
    "BoxscoreResponse",
    "DailyLoadResult",
    "DailyLoader",
    "GameIdMismatchError",
    "GameLoadResult",
    "GameLoader",
    "GameOutcome",
    "GameResponseBase",
    "LandingResponse",
    "PlayByPlayLoadResult",
    "PlayByPlayLoader",
    "PlayByPlayResponse",
    "ScheduleDay",
    "ScheduleDayNotFoundError",
    "ScheduleGame",
    "ScheduleLoader",
    "ScheduleResponse",
    "TeamRef",
    "assert_game_id_matches_season",
    "boxscore_url",
    "filter_ingestible",
    "landing_url",
    "play_by_play_url",
    "schedule_url",
    "select_day",
    "yesterday_in_toronto",
]
