"""Per-endpoint pydantic models for NHL game-level responses.

The PR-A spike (``docs/ideas/pra-spike-notes.md`` §2) found that
``landing``, ``boxscore``, and ``play-by-play`` overlap heavily on
top-level metadata but each has unique fields. Rather than collapse
them into a single all-optional schema, we model each endpoint
separately and let the silver layer (M3) reconcile.

These models are deliberately *not* exhaustive. The bronze layer's
contract is "preserve the verbatim JSON" — see ``response_json`` in
:mod:`puckbunny.storage.parquet`. The pydantic models exist to:

1. Validate the small set of fields we promote into the typed
   envelope columns (``id``, ``season``, ``gameDate``).
2. Catch upstream schema drift on those fields early, with a clear
   error, instead of letting it land silently in bronze.
3. Run the spike-§7 game-id-vs-season invariant on every fetched
   game.

Everything else from the API is preserved verbatim in the
``response_json`` column for re-parsing later. ``extra="allow"`` on
each model makes that explicit — added upstream fields neither break
parsing nor get silently dropped from validation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, model_validator

if TYPE_CHECKING:
    from typing import Self


__all__ = [
    "BoxscoreResponse",
    "GameResponseBase",
    "GoalieSummaryResponse",
    "GoalieSummaryRow",
    "LandingResponse",
    "PlayByPlayResponse",
    "ScheduleDay",
    "ScheduleGame",
    "ScheduleResponse",
    "SkaterSummaryResponse",
    "SkaterSummaryRow",
    "TeamRef",
    "TeamSummaryResponse",
    "TeamSummaryRow",
    "assert_game_id_matches_season",
]


class TeamRef(BaseModel):
    """Minimal away/home team identifier carried on game-level responses.

    The full team payload (logos, score, sog, localized names, etc.) is
    preserved in ``response_json``; the silver layer reads it from
    there.  We pin only ``id`` + ``abbrev`` because those are the join
    keys to ``dim_team`` and they must be present.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    abbrev: str


class GameResponseBase(BaseModel):
    """Shared subset across NHL game-level endpoints.

    Spike §6: ``id`` is the canonical natural-key field on every
    game-level response. Spike §7: the leading 4 digits of ``id``
    encode the season-start year, which matches the leading 4 digits
    of ``season`` (an int like ``20252026``). The
    :meth:`_validate_game_id_format` post-validator enforces this on
    every parsed payload — cheap insurance against an upstream
    encoding change.

    Note: ``season`` is an ``int`` in the live API
    (e.g. ``20252026``), not a string. The bronze envelope stores it
    as a string; the loader is responsible for the ``str(...)``
    conversion at envelope-build time.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    season: int
    gameType: int
    gameDate: date
    gameState: str
    startTimeUTC: datetime
    awayTeam: TeamRef
    homeTeam: TeamRef

    @model_validator(mode="after")
    def _validate_game_id_format(self) -> Self:
        """Assert ``game_id // 1_000_000 == int(str(season)[:4])``.

        Per spike notes §7: the NHL game-ID encoding is
        ``{season_start_year:4}{game_type:02}{game_seq:04}``. If this
        ever stops holding, every downstream join keyed on
        ``(season, game_id)`` is at risk; failing at parse time is
        cheaper than debugging silent corruption later.
        """
        season_year = int(str(self.season)[:4])
        encoded_year = self.id // 1_000_000
        if encoded_year != season_year:
            raise ValueError(
                f"NHL game-id format violation: id={self.id} encodes "
                f"season-start-year {encoded_year}, but season={self.season} "
                f"begins {season_year}. Upstream encoding may have changed."
            )
        return self


class LandingResponse(GameResponseBase):
    """``/v1/gamecenter/{gameId}/landing`` typed shape.

    Spike-confirmed top-level fields unique to landing include
    ``tiesInUse``, ``otInUse``, ``shootoutInUse``, and
    ``venueTimezone``. None are pinned here because none drive the
    bronze envelope columns; they ride along in ``response_json`` and
    silver picks them up.
    """


class BoxscoreResponse(GameResponseBase):
    """``/v1/gamecenter/{gameId}/boxscore`` typed shape.

    The fields that justify hitting this endpoint at all —
    ``playerByGameStats`` (per-player skater/goalie game stats) and
    ``gameOutcome`` — are pinned as required so a regression that
    drops them surfaces here, not three pipeline stages later.
    """

    playerByGameStats: dict[str, Any]
    gameOutcome: dict[str, Any]


class PlayByPlayResponse(GameResponseBase):
    """``/v1/gamecenter/{gameId}/play-by-play`` typed shape.

    The fields that justify hitting this endpoint at all — ``plays``
    (event-level play-by-play) and ``rosterSpots`` (per-game dressed
    roster) — are pinned as required, so a regression that drops them
    fails at parse time rather than landing a useless payload in
    bronze.

    Per ``docs/ideas/prd-pbp-keys.md``, per-event ``details`` shapes
    vary by ``typeDescKey`` and a few event types (``period-start``,
    ``period-end``, ``game-end``) have no ``details`` block at all. We
    deliberately do **not** model ``plays[*].details`` here. The bronze
    contract is "preserve the verbatim payload"; silver (M3) handles
    the per-event-type unnest where it can fail loudly without
    breaking ingest. ``extra="allow"`` (inherited from
    :class:`GameResponseBase`) means future ``typeDescKey`` values land
    quietly in bronze.
    """

    plays: list[dict[str, Any]]
    rosterSpots: list[dict[str, Any]]


class ScheduleGame(GameResponseBase):
    """One game in a ``/v1/schedule/{date}`` response.

    Extends :class:`GameResponseBase` so the spike-§7 game-id-vs-season
    invariant runs on every game returned by the schedule endpoint.
    The schedule's per-game payload carries the same canonical metadata
    columns as the gamecenter endpoints (``id``, ``season``,
    ``gameType``, ``gameDate``, ``gameState``, ``startTimeUTC``,
    ``awayTeam``, ``homeTeam``) plus extras (``venue``,
    ``periodDescriptor``, ``threeMinRecap``, …) that ride along in
    ``model_extra``.

    Note that ``gameState`` here can be any of ``FUT``, ``PRE``,
    ``LIVE``, ``CRIT``, ``OFF``, ``FINAL``, ``PPD`` — the schedule
    walker filters to the "ingestible" set
    (:data:`puckbunny.ingestion.nhl.endpoints.INGESTIBLE_GAME_STATES`).
    """


class ScheduleDay(BaseModel):
    """One day's entry inside ``ScheduleResponse.gameWeek``.

    Per spike notes §1, the schedule endpoint returns a *week* of games
    keyed by ``gameWeek[*].date``, not just the requested date. The
    daily walker iterates this list and selects the matching day. We
    pin only the two fields the walker needs; ``dayAbbrev`` /
    ``numberOfGames`` and friends are preserved via ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow")

    date: date
    games: list[ScheduleGame]


class ScheduleResponse(BaseModel):
    """``/v1/schedule/{YYYY-MM-DD}`` typed shape.

    Top-level fields like ``previousStartDate`` / ``nextStartDate`` /
    ``preSeasonStartDate`` exist but the daily walker doesn't need
    them. Any future additions ride in ``model_extra``.
    """

    model_config = ConfigDict(extra="allow")

    gameWeek: list[ScheduleDay]


def assert_game_id_matches_season(game_id: int, season: int | str) -> None:
    """Standalone version of the spike §7 invariant.

    Useful for callers that have raw values (e.g. the schedule loader
    in PR-E) and want to assert before constructing a full response
    model. Raises ``ValueError`` on mismatch.
    """
    season_year = int(str(season)[:4])
    encoded_year = game_id // 1_000_000
    if encoded_year != season_year:
        raise ValueError(
            f"NHL game-id format violation: id={game_id} encodes "
            f"season-start-year {encoded_year}, but season={season} "
            f"begins {season_year}."
        )


# ---------------------------------------------------------------------------
# Season-scoped summary endpoints (PR-F1).
#
# Per the PR-F0 spike (``docs/ideas/prf-stats-rest-spike-notes.md``):
# every season-summary response is shaped as
#
#     {"data": [<row>, <row>, ...], "total": N}
#
# and ``len(data) == total`` is the contract — the loader asserts this
# before writing bronze. Per-row schemas pin only the fields that
# downstream silver promotion can rely on; everything else rides along
# in ``response_json`` via ``extra="allow"``.
#
# Row schemas overlap on common fields (``seasonId``,
# ``playerId``/``teamId``, ``gamesPlayed``, ``goals``, ``assists``,
# ``points``) but diverge enough on the rest (faceoff %, save %,
# team-only fields like ``pointPct`` and ``regulationAndOtWins``) to
# not bother with a shared base. The spike notes recommend per-endpoint
# row classes for this reason.
# ---------------------------------------------------------------------------


class _SeasonSummaryRowBase(BaseModel):
    """Common ``extra="allow"`` config for every season-summary row.

    Not exposed in ``__all__`` — concrete subclasses are. Exists only
    to factor the ``model_config`` and the ``seasonId`` pin that every
    row carries (the spike confirmed this on first row of every
    response).
    """

    model_config = ConfigDict(extra="allow")

    seasonId: int


class SkaterSummaryRow(_SeasonSummaryRowBase):
    """One row in a ``skater/summary`` response's ``data`` array.

    Pinned fields are the ones the loader / silver-layer M3 work will
    rely on: identity (``playerId``), volume (``gamesPlayed``), and
    the canonical scoring stats (``goals``, ``assists``, ``points``).
    Everything else (``shots``, ``faceoffWinPct``, ``timeOnIcePerGame``,
    ``teamAbbrevs``, …) rides along via ``extra="allow"``; silver picks
    them up from the verbatim ``response_json`` envelope.
    """

    playerId: int
    gamesPlayed: int
    goals: int
    assists: int
    points: int


class GoalieSummaryRow(_SeasonSummaryRowBase):
    """One row in a ``goalie/summary`` response's ``data`` array.

    Pinned fields mirror :class:`SkaterSummaryRow` for identity +
    volume; goalie-specific stats (``savePct``, ``goalsAgainstAverage``,
    ``shutouts``, …) are preserved via ``extra="allow"``. The schema
    is intentionally permissive about which optional goalie metrics
    appear — partial-season aggregates can omit fields entirely.
    """

    playerId: int
    gamesPlayed: int


class TeamSummaryRow(_SeasonSummaryRowBase):
    """One row in a ``team/summary`` response's ``data`` array.

    Pinned fields are identity (``teamId``) and volume (``gamesPlayed``).
    Team-only metrics like ``pointPct``, ``regulationAndOtWins``, and
    ``goalsForPerGame`` ride along via ``extra="allow"``.
    """

    teamId: int
    gamesPlayed: int


class _SeasonSummaryResponseBase(BaseModel):
    """Shared ``{data, total}`` envelope contract.

    Per spike §2 the response shape is uniform across the three
    season-summary endpoints; the only thing that varies is the row
    type inside ``data``. Concrete subclasses re-declare ``data`` with
    the appropriate row class so pydantic validates each row.

    The ``len(data) == total`` invariant is enforced via a
    post-validator so any future re-parse of the bronze envelope (not
    just the loader's defensive check at fetch time) raises on
    mismatch.
    """

    model_config = ConfigDict(extra="allow")

    total: int

    @model_validator(mode="after")
    def _validate_data_total_match(self) -> Self:
        """Assert ``len(data) == total``.

        Per PR-F0 spike §2 this is the surface's pagination contract
        when ``limit=-1`` — preserved as a model invariant so re-parse
        catches drift even if the original fetch's defensive check is
        bypassed.
        """
        # ``data`` is declared on each concrete subclass; access via
        # attribute lookup so this validator is reusable.
        data: list[Any] = getattr(self, "data", [])
        if len(data) != self.total:
            raise ValueError(
                f"season-summary envelope contract violation: total={self.total} "
                f"but len(data)={len(data)}. limit=-1 is supposed to return "
                f"the full set in one response."
            )
        return self


class SkaterSummaryResponse(_SeasonSummaryResponseBase):
    """``/stats/rest/en/skater/summary`` typed shape."""

    data: list[SkaterSummaryRow]


class GoalieSummaryResponse(_SeasonSummaryResponseBase):
    """``/stats/rest/en/goalie/summary`` typed shape."""

    data: list[GoalieSummaryRow]


class TeamSummaryResponse(_SeasonSummaryResponseBase):
    """``/stats/rest/en/team/summary`` typed shape."""

    data: list[TeamSummaryRow]
