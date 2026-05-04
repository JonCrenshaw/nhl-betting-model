"""URL builders and constants for the NHL public API surfaces.

D1 of ``docs/milestones/m2-nhl-ingestion.md`` commits us to the modern
NHL API. Two distinct surfaces are in scope, each with its own
versioning convention:

* ``https://api-web.nhle.com`` — game-level + schedule + roster
  endpoints, all under ``/v1/...``. Validated by the PR-A spike.
* ``https://api.nhle.com/stats/rest/en`` — season-scoped summary
  endpoints (skater / goalie / team). Note the mandatory ``en``
  locale segment; this surface does **not** use ``/v1/``. Validated
  by the PR-F0 spike (``docs/ideas/prf-stats-rest-spike-notes.md``
  §"Surprises" #1).

Paths are kept as templates (``"…/{gameId}/landing"``) for the bronze
envelope's ``endpoint`` column, where the *template* — not a
substituted URL — is the canonical identifier of which API surface
produced a row. Concrete URLs come from the matching ``*_url`` helper.
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


# ---------------------------------------------------------------------------
# Stats-rest surface (PR-F): season-scoped summary endpoints.
#
# Distinct host + path convention from ``api-web.nhle.com`` above. Per
# the PR-F0 spike (``docs/ideas/prf-stats-rest-spike-notes.md``):
#
# * Base path is ``/stats/rest/en/...`` — a mandatory locale segment,
#   no ``/v1/``. The first probe run hit 404s with the (incorrect)
#   ``/v1/`` path the M2 plan originally documented.
# * One GET per ``(endpoint, season)`` with ``cayenneExp=seasonId={S}``
#   and ``limit=-1`` returns the whole result set in a
#   ``{"data": [...], "total": N}`` envelope. The loader asserts
#   ``len(data) == total`` defensively before writing bronze.
# * No ``gameTypeId`` filter for PR-F1 — unfiltered response combines
#   regular + playoff aggregates for finalized seasons; revisit in
#   ADR-0003 if M4 modeling needs the split.
# ---------------------------------------------------------------------------

#: Base URL of the stats-rest surface. No trailing slash. Note the
#: ``/en`` locale segment — distinct from ``api-web.nhle.com``'s
#: ``/v1/`` versioning convention.
NHL_STATS_REST_BASE_URL: str = "https://api.nhle.com/stats/rest/en"

#: Endpoint templates used as the canonical identifier in the bronze
#: ``endpoint`` column. The path segments match the NHL stats-rest URL
#: shape so cross-referencing is friction-free.
SKATER_SUMMARY_ENDPOINT_TEMPLATE: str = "/stats/rest/en/skater/summary"
GOALIE_SUMMARY_ENDPOINT_TEMPLATE: str = "/stats/rest/en/goalie/summary"
TEAM_SUMMARY_ENDPOINT_TEMPLATE: str = "/stats/rest/en/team/summary"

#: Sentinel ``limit`` value the stats-rest surface honors as "return
#: every row in one response." Per spike §2 — anything else, including
#: omitting ``limit`` entirely, caps at 50 (default) or 100 (max
#: explicit cap). ``-1`` is the only value that returns the full set.
STATS_REST_LIMIT_ALL: int = -1


def _format_season_id(season: int | str) -> str:
    """Normalize a season identifier to the 8-char ``YYYYYYYY`` form.

    Accepts ``int`` (``20242025``) or ``str`` (``"20242025"``). The
    stats-rest ``cayenneExp=seasonId=...`` query parameter takes the
    digit string; the caller's choice between int and str is just
    ergonomics — both forms are valid in the codebase.
    """
    s = str(season)
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"season must be 8 digits like '20242025', got {season!r}")
    return s


def skater_summary_url(season: int | str) -> str:
    """Return the absolute ``skater/summary`` URL for ``season``.

    Always issued with ``limit=-1`` (see :data:`STATS_REST_LIMIT_ALL`)
    so the response carries every skater for the season in one shot;
    the loader asserts ``len(data) == total`` before writing bronze.
    The returned URL has no query string — callers (or the loader) add
    the ``cayenneExp`` and ``limit`` params at request time so the
    template-vs-substituted distinction stays clean.
    """
    _format_season_id(season)  # validate eagerly; result not interpolated
    return f"{NHL_STATS_REST_BASE_URL}/skater/summary"


def goalie_summary_url(season: int | str) -> str:
    """Return the absolute ``goalie/summary`` URL for ``season``."""
    _format_season_id(season)
    return f"{NHL_STATS_REST_BASE_URL}/goalie/summary"


def team_summary_url(season: int | str) -> str:
    """Return the absolute ``team/summary`` URL for ``season``."""
    _format_season_id(season)
    return f"{NHL_STATS_REST_BASE_URL}/team/summary"


def season_summary_query_params(season: int | str) -> dict[str, object]:
    """Return the query-param dict for one season-summary fetch.

    Captures the wire-truth shape the loader actually puts on the URL,
    so the bronze envelope's ``endpoint_params_json`` column reflects
    what we sent — per D3 in the M2 plan ("the exact parameter dict
    used"). Surfaced here rather than inlined in the loader so the
    schema-of-the-call lives next to the URL definition.
    """
    return {
        "cayenneExp": f"seasonId={_format_season_id(season)}",
        "limit": STATS_REST_LIMIT_ALL,
    }


def season_start_date(season: int | str) -> date:
    """Return Oct 1 of the season's start year — the bronze ``event_date``
    sentinel for season-scoped endpoints.

    Per the PR-F1 design discussion: season-summary rows don't have a
    natural per-fetch event date (they aggregate a whole season's
    activity). Oct 1 is a stable, sortable sentinel that matches the
    ``seasonId`` convention (``20242025`` begins in 2024) and sits
    appropriately *after* any pre-season games (which run in mid- to
    late-September and live in their own bronze partition anyway).

    Important: bronze ``event_date`` is NOT a season-membership filter
    for season-summary rows. The ``season`` column is. Silver should
    filter by ``WHERE season = '20242025'`` rather than by
    ``event_date`` ranges.
    """
    season_str = _format_season_id(season)
    start_year = int(season_str[:4])
    return date(start_year, 10, 1)
