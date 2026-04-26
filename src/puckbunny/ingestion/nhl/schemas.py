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
    "LandingResponse",
    "TeamRef",
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
