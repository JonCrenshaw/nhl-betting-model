"""Schedule fetcher + daily incremental orchestrator.

Per ``docs/milestones/m2-nhl-ingestion.md`` PR-E, this module wires
the per-day ingestion loop:

1. :class:`ScheduleLoader` calls ``/v1/schedule/{date}`` (which returns
   a *week* of games, per spike notes §1) and validates the response
   shape via :class:`puckbunny.ingestion.nhl.schemas.ScheduleResponse`.
2. :class:`DailyLoader` selects the matching day from ``gameWeek``,
   filters to games in
   :data:`puckbunny.ingestion.nhl.endpoints.INGESTIBLE_GAME_STATES`
   (``{FINAL, OFF}``), and for each eligible game fetches landing +
   boxscore via :class:`puckbunny.ingestion.nhl.games.GameLoader` and
   play-by-play via
   :class:`puckbunny.ingestion.nhl.play_by_play.PlayByPlayLoader`,
   skipping games whose three endpoints are already recorded in the
   manifest.

Idempotency is at the game level: if any one of the three game-level
endpoints is missing from the manifest for a given ``game_id``, the
daily walker re-fetches all three. This trades a small amount of
duplicated landing/boxscore writes (in the rare partial-failure case)
for substantially simpler logic. The manifest entries are still
recorded per endpoint, so PR-G's backfill can opt for per-endpoint
dedupe if needed.

The daily CLI default — "yesterday in America/Toronto" — lives here
as :func:`yesterday_in_toronto` so it stays close to its only caller
(the ``daily`` subcommand).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog
from pydantic import ValidationError

from puckbunny.ingestion.manifest import (
    ManifestEntry,
    ManifestStore,
    build_entry,
    new_run_id,
)
from puckbunny.ingestion.nhl.endpoints import (
    BOXSCORE_ENDPOINT_TEMPLATE,
    INGESTIBLE_GAME_STATES,
    LANDING_ENDPOINT_TEMPLATE,
    PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
    SCHEDULE_ENDPOINT_TEMPLATE,
    schedule_url,
)
from puckbunny.ingestion.nhl.schemas import (
    ScheduleDay,
    ScheduleGame,
    ScheduleResponse,
)

if TYPE_CHECKING:
    from datetime import date

    from puckbunny.http.client import RateLimitedClient
    from puckbunny.ingestion.nhl.games import GameLoader, GameLoadResult
    from puckbunny.ingestion.nhl.play_by_play import (
        PlayByPlayLoader,
        PlayByPlayLoadResult,
    )
    from puckbunny.storage.parquet import WriteResult


#: IANA name for the daily-loader default. NHL games are scheduled in
#: Eastern time so "yesterday's slate" most cleanly maps to America/
#: Toronto's calendar day, not UTC's. ``zoneinfo.ZoneInfo`` reads from
#: the ``tzdata`` wheel on Windows / slim Linux (added in
#: ``pyproject.toml``).
TORONTO_TZ: ZoneInfo = ZoneInfo("America/Toronto")


class ScheduleDayNotFoundError(LookupError):
    """Raised when ``target_date`` isn't present in the response's ``gameWeek``.

    The schedule endpoint anchors a week around the requested date, so
    in practice the requested date is always one of the seven entries.
    If it isn't, something has gone sideways — either we sent a
    malformed date or the API's week-window logic changed. Failing
    loudly beats silently iterating an empty list.
    """


@dataclass(frozen=True)
class GameOutcome:
    """One game's daily-load result.

    ``landing`` / ``boxscore`` / ``play_by_play`` are ``None`` when
    that endpoint was skipped because the manifest already had it (or
    because the game itself was skipped — see ``skipped``).
    """

    game_id: int
    skipped: bool
    landing: WriteResult | None = None
    boxscore: WriteResult | None = None
    play_by_play: WriteResult | None = None


@dataclass(frozen=True)
class DailyLoadResult:
    """Summary of one :meth:`DailyLoader.load_date` invocation."""

    target_date: date
    ingest_date: date
    run_id: str
    games_in_schedule: int
    games_eligible: int
    games_loaded: int
    games_skipped: int
    outcomes: list[GameOutcome] = field(default_factory=list)


class ScheduleLoader:
    """Fetch + validate one ``/v1/schedule/{date}`` response.

    Kept thin: no manifest interaction here. The schedule isn't bronze
    in M2 — silver doesn't need a snapshot of the schedule to function,
    and re-fetching is cheap. PR-G can revisit if a paper trail of
    schedule snapshots becomes useful for backtest reproducibility.
    """

    def __init__(self, client: RateLimitedClient) -> None:
        self._client = client
        self._log = structlog.get_logger(__name__)

    def fetch(self, target_date: date) -> ScheduleResponse:
        """Fetch and validate the schedule containing ``target_date``.

        Returns the parsed :class:`ScheduleResponse`. Raises
        :class:`pydantic.ValidationError` on shape drift and
        :class:`puckbunny.http.client.RetryableStatusError` (or
        ``httpx.HTTPStatusError``) on exhausted-retry HTTP failures.
        """
        url = schedule_url(target_date)
        log = self._log.bind(target_date=target_date.isoformat(), url=url)
        log.info("nhl_schedule_fetch_start")
        response = self._client.get(url)
        try:
            parsed = ScheduleResponse.model_validate_json(response.text)
        except ValidationError:
            log.error("nhl_schedule_validation_failed")
            raise
        log.info(
            "nhl_schedule_fetch_complete",
            days_returned=len(parsed.gameWeek),
            total_games=sum(len(d.games) for d in parsed.gameWeek),
        )
        return parsed


def select_day(schedule: ScheduleResponse, target_date: date) -> ScheduleDay:
    """Return the ``ScheduleDay`` whose ``date`` equals ``target_date``.

    Raises :class:`ScheduleDayNotFoundError` if no match. Surfaced as a
    free function (rather than a method on ScheduleResponse) so tests
    can exercise the lookup logic without instantiating a full schema.
    """
    for day in schedule.gameWeek:
        if day.date == target_date:
            return day
    raise ScheduleDayNotFoundError(
        f"target_date {target_date.isoformat()} not present in schedule "
        f"gameWeek (saw: {[d.date.isoformat() for d in schedule.gameWeek]})"
    )


def filter_ingestible(games: list[ScheduleGame]) -> list[ScheduleGame]:
    """Return only games whose ``gameState`` is in
    :data:`INGESTIBLE_GAME_STATES`.

    Order-preserving so the daily walker processes games in the
    schedule's natural order (typically by ``startTimeUTC``).
    """
    return [g for g in games if g.gameState in INGESTIBLE_GAME_STATES]


class DailyLoader:
    """Compose schedule fetch + per-game ingestion + manifest dedupe.

    The orchestrator owns no IO of its own — every external interaction
    is delegated to an injected collaborator. Tests substitute mock
    loaders + a manifest backed by
    :class:`puckbunny.storage.local.LocalFilesystemStorage`.
    """

    def __init__(
        self,
        schedule_loader: ScheduleLoader,
        game_loader: GameLoader,
        pbp_loader: PlayByPlayLoader,
        manifest: ManifestStore,
    ) -> None:
        self._schedule_loader = schedule_loader
        self._game_loader = game_loader
        self._pbp_loader = pbp_loader
        self._manifest = manifest
        self._log = structlog.get_logger(__name__)

    def load_date(
        self,
        target_date: date,
        *,
        ingest_date: date | None = None,
    ) -> DailyLoadResult:
        """Fetch schedule, ingest every eligible game, return a summary.

        Args:
            target_date: The NHL ``gameDate`` to ingest.
            ingest_date: Bronze partition key override. Defaults to the
                UTC date at call time, matching the gamecenter loaders.

        Returns:
            :class:`DailyLoadResult` with per-game outcomes.
        """
        ingest_date = ingest_date or datetime.now(UTC).date()
        run_id = new_run_id()
        log = self._log.bind(
            target_date=target_date.isoformat(),
            ingest_date=ingest_date.isoformat(),
            run_id=run_id,
        )
        log.info("nhl_daily_load_start")

        schedule = self._schedule_loader.fetch(target_date)
        day = select_day(schedule, target_date)
        eligible = filter_ingestible(day.games)
        log.info(
            "nhl_daily_filter",
            games_in_schedule=len(day.games),
            games_eligible=len(eligible),
        )

        outcomes: list[GameOutcome] = []
        loaded_count = 0
        skipped_count = 0
        new_manifest_entries: list[ManifestEntry] = []

        for game in eligible:
            outcome, entries = self._load_one_game(
                game=game,
                ingest_date=ingest_date,
                run_id=run_id,
            )
            outcomes.append(outcome)
            new_manifest_entries.extend(entries)
            if outcome.skipped:
                skipped_count += 1
            else:
                loaded_count += 1

        if new_manifest_entries:
            self._manifest.append_many(new_manifest_entries)

        result = DailyLoadResult(
            target_date=target_date,
            ingest_date=ingest_date,
            run_id=run_id,
            games_in_schedule=len(day.games),
            games_eligible=len(eligible),
            games_loaded=loaded_count,
            games_skipped=skipped_count,
            outcomes=outcomes,
        )
        log.info(
            "nhl_daily_load_complete",
            games_loaded=loaded_count,
            games_skipped=skipped_count,
        )
        return result

    # --- internals ---

    def _load_one_game(
        self,
        *,
        game: ScheduleGame,
        ingest_date: date,
        run_id: str,
    ) -> tuple[GameOutcome, list[ManifestEntry]]:
        """Ingest one schedule game's three endpoints.

        Returns the per-game outcome and the manifest entries to
        append. Skips the entire game when all three endpoints are
        already in the manifest (the common idempotent re-run case).
        """
        scope = str(game.id)
        already_have = {
            LANDING_ENDPOINT_TEMPLATE: self._manifest.has(LANDING_ENDPOINT_TEMPLATE, scope),
            BOXSCORE_ENDPOINT_TEMPLATE: self._manifest.has(BOXSCORE_ENDPOINT_TEMPLATE, scope),
            PLAY_BY_PLAY_ENDPOINT_TEMPLATE: self._manifest.has(
                PLAY_BY_PLAY_ENDPOINT_TEMPLATE, scope
            ),
        }
        if all(already_have.values()):
            self._log.info("nhl_daily_game_skipped", game_id=game.id)
            return (
                GameOutcome(game_id=game.id, skipped=True),
                [],
            )

        # Game-level fetch: landing + boxscore via GameLoader, then
        # play-by-play. We always fetch all three when any are missing,
        # to keep this orchestrator simple — see module docstring.
        game_result: GameLoadResult = self._game_loader.load_one(game.id, ingest_date=ingest_date)
        pbp_result: PlayByPlayLoadResult = self._pbp_loader.load_one(
            game.id, ingest_date=ingest_date
        )

        entries = [
            build_entry(
                run_id=run_id,
                endpoint=LANDING_ENDPOINT_TEMPLATE,
                scope_key=scope,
                rows=game_result.landing.rows,
                bytes_written=game_result.landing.bytes,
            ),
            build_entry(
                run_id=run_id,
                endpoint=BOXSCORE_ENDPOINT_TEMPLATE,
                scope_key=scope,
                rows=game_result.boxscore.rows,
                bytes_written=game_result.boxscore.bytes,
            ),
            build_entry(
                run_id=run_id,
                endpoint=PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
                scope_key=scope,
                rows=pbp_result.play_by_play.rows,
                bytes_written=pbp_result.play_by_play.bytes,
            ),
        ]
        outcome = GameOutcome(
            game_id=game.id,
            skipped=False,
            landing=game_result.landing,
            boxscore=game_result.boxscore,
            play_by_play=pbp_result.play_by_play,
        )
        return outcome, entries


def yesterday_in_toronto(*, now: datetime | None = None) -> date:
    """Return ``yesterday`` in :data:`TORONTO_TZ`, the daily CLI default.

    NHL games are scheduled in Eastern time and the ``gameDate`` field
    on every endpoint is the calendar date in that zone. "Yesterday in
    Toronto" lets the daily loader run any time the next morning UTC
    and still pick up the previous Eastern slate, including games that
    finish past midnight UTC.

    Args:
        now: Override the wall clock — used by tests to make the
            default deterministic. Production callers leave this unset.
    """
    current = now or datetime.now(TORONTO_TZ)
    if current.tzinfo is None:
        # Defensive: if a caller passes a naive ``now``, assume Toronto
        # local time rather than silently UTC-coercing.
        current = current.replace(tzinfo=TORONTO_TZ)
    return (current.astimezone(TORONTO_TZ) - timedelta(days=1)).date()


__all__ = [
    "SCHEDULE_ENDPOINT_TEMPLATE",
    "TORONTO_TZ",
    "DailyLoadResult",
    "DailyLoader",
    "GameOutcome",
    "ScheduleDayNotFoundError",
    "ScheduleLoader",
    "filter_ingestible",
    "select_day",
    "yesterday_in_toronto",
]
