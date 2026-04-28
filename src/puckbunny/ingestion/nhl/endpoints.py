"""URL builders and constants for the NHL ``api-web.nhle.com`` surface.

D1 of ``docs/milestones/m2-nhl-ingestion.md`` commits us to the modern
NHL API at ``https://api-web.nhle.com``. The PR-A spike confirmed
``landing``, ``boxscore``, ``play-by-play``, and ``schedule`` return
200s with our identifying ``User-Agent`` and no auth.

Paths are kept as templates (``"…/{gameId}/landing"``) for the bronze
envelope's ``endpoint`` column, where the *template* — not a
substituted URL — is the canonical identifier of which API surface
produced a row. Concrete URLs come from the matching ``*_url`` helper.

PR-F adds the season-summaries surface on
``api.nhle.com/stats/rest/v1``.
"""

from __future__ import annotations

from datetime import date

#: Base URL of the modern, web-facing NHL API. No trailing slash.
NHL_API_BASE_URL: str = "https://api-web.nhle.com"

#: Endpoint template used as the canonical identifier in the bronze
#: ``endpoint`` column. The placeholder name matches the NHL API's own
#: ``gameId`` term so cross-referencing their docs is friction-free.
LANDING_ENDPOINT_TEMPLATE: str = "/v1/gamecenter/{gameId}/landing"
BOXSCORE_ENDPOINT_TEMPLATE: str = "/v1/gamecenter/{gameId}/boxscore"
PLAY_BY_PLAY_ENDPOINT_TEMPLATE: str = "/v1/gamecenter/{gameId}/play-by-play"
SCHEDULE_ENDPOINT_TEMPLATE: str = "/v1/schedule/{date}"

#: Game states that mean "this game is finished and safe to ingest".
#: Per spike notes §1: the schedule endpoint returns ``OFF`` (not
#: ``FINAL``) for concluded playoff games, so the daily walker must
#: accept both. Anything else (``LIVE``, ``FUT``, ``PRE``, ``CRIT``,
#: ``PPD``) is skipped.
INGESTIBLE_GAME_STATES: frozenset[str] = frozenset({"FINAL", "OFF"})


def landing_url(game_id: int) -> str:
    """Return the absolute ``landing`` URL for ``game_id``."""
    return f"{NHL_API_BASE_URL}/v1/gamecenter/{game_id}/landing"


def boxscore_url(game_id: int) -> str:
    """Return the absolute ``boxscore`` URL for ``game_id``."""
    return f"{NHL_API_BASE_URL}/v1/gamecenter/{game_id}/boxscore"


def play_by_play_url(game_id: int) -> str:
    """Return the absolute ``play-by-play`` URL for ``game_id``.

    PxP is the largest per-game payload (~131 KB JSON / ~16 KB Parquet,
    per the PR-A spike). Same URL shape as the other two game-level
    endpoints; carries ``plays`` and ``rosterSpots`` lists in addition
    to the shared game metadata.
    """
    return f"{NHL_API_BASE_URL}/v1/gamecenter/{game_id}/play-by-play"


def schedule_url(target: date | str) -> str:
    """Return the absolute ``schedule`` URL for ``target``.

    Per spike notes §1, the schedule endpoint returns a *week* of games
    keyed by ``gameWeek[*].date``, not just the requested date. The
    daily walker (``schedule.py``) iterates ``gameWeek[*]`` filtered to
    the requested date — but the URL only takes a single date string
    that anchors which week is returned.

    ``target`` may be a :class:`datetime.date` or an already-formatted
    ``YYYY-MM-DD`` string. We accept both so callers that already have
    the formatted string (e.g. the CLI ``--date`` flag) don't have to
    round-trip through ``date.fromisoformat``.
    """
    if isinstance(target, date):
        date_str = target.isoformat()
    else:
        # Validate format eagerly so a bad string fails here, not on
        # the wire. ``fromisoformat`` raises ``ValueError`` on malformed
        # input — let it propagate.
        date_str = date.fromisoformat(target).isoformat()
    return f"{NHL_API_BASE_URL}/v1/schedule/{date_str}"
