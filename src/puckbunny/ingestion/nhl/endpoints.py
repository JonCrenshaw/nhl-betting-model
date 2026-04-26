"""URL builders and constants for the NHL ``api-web.nhle.com`` surface.

D1 of ``docs/milestones/m2-nhl-ingestion.md`` commits us to the modern
NHL API at ``https://api-web.nhle.com``. The PR-A spike confirmed
``landing``, ``boxscore``, and ``play-by-play`` return 200s with our
identifying ``User-Agent`` and no auth.

Paths are kept as templates (``"…/{gameId}/landing"``) for the bronze
envelope's ``endpoint`` column, where the *template* — not a
substituted URL — is the canonical identifier of which API surface
produced a row. Concrete URLs come from the matching ``*_url`` helper.

PR-D will add a ``play_by_play_url`` here; PR-E adds ``schedule_url``.
"""

from __future__ import annotations

#: Base URL of the modern, web-facing NHL API. No trailing slash.
NHL_API_BASE_URL: str = "https://api-web.nhle.com"

#: Endpoint template used as the canonical identifier in the bronze
#: ``endpoint`` column. The placeholder name matches the NHL API's own
#: ``gameId`` term so cross-referencing their docs is friction-free.
LANDING_ENDPOINT_TEMPLATE: str = "/v1/gamecenter/{gameId}/landing"
BOXSCORE_ENDPOINT_TEMPLATE: str = "/v1/gamecenter/{gameId}/boxscore"


def landing_url(game_id: int) -> str:
    """Return the absolute ``landing`` URL for ``game_id``."""
    return f"{NHL_API_BASE_URL}/v1/gamecenter/{game_id}/landing"


def boxscore_url(game_id: int) -> str:
    """Return the absolute ``boxscore`` URL for ``game_id``."""
    return f"{NHL_API_BASE_URL}/v1/gamecenter/{game_id}/boxscore"
