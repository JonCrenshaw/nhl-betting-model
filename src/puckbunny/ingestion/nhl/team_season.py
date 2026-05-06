"""Per-team-per-season NHL bronze loader: ``roster`` +
``club-schedule-season`` for one ``(season, team)`` pair.

Sister to :mod:`puckbunny.ingestion.nhl.season_summaries` and
:mod:`puckbunny.ingestion.nhl.games` — same PR-B primitives
(rate-limited HTTP + typed envelope + bronze partition writer), same
"one fetch = one envelope row" bronze invariant. Lives on the
``api-web.nhle.com`` surface validated by PR-A; the per-endpoint
payload shapes were locked in by the PR-F2 spike
(``docs/ideas/prf2-spike-notes.md``).

Cadence note. Like PR-F1, this loader is intentionally cadence-agnostic
— it always fetches when called, records the manifest entry
unconditionally, and leaves "should we skip because we already have
this?" to the caller. Per the PR-F2 open-questions doc §3, M10 will
need three distinct schedules:

1. **Backfill** (PR-G): ``manifest.has(endpoint, scope_key)`` gate;
   one-shot per ``(season, team, endpoint)``.
2. **Weekly + trade-deadline-daily roster** for the in-progress season:
   bypass gating (rosters change continuously through trades, callups,
   IR moves; gating would suppress fresh snapshots).
3. **Post-schedule-release club-schedule** for the upcoming season:
   gate via ``manifest.has()``; once per ``(season, team)`` is correct
   and re-fetch is wasteful unless a postponement triggers it.

Full M10 design parked in
``docs/ideas/team-season-cadence-gating.md`` (sister to PR-F1's
``season-summaries-cadence-gating.md``).

404 handling. Per the PR-F2 spike, requesting a ``(team, season)``
pair that didn't exist (e.g. ``UTA`` for 2023-24, ``ARI`` for 2025-26)
returns HTTP 404 with an HTML body. The loader treats 404 as
**log-and-skip per endpoint**, returning ``None`` for that endpoint's
``WriteResult`` slot. Other HTTP errors propagate per
:class:`puckbunny.http.client.RateLimitedClient`'s contract. This keeps
backfill loops resilient to franchise edges without silently swallowing
real errors.

Bronze row granularity (matches PR-F1). One envelope row per fetch —
the verbatim API body lands in ``response_json``, ``entity_id`` is
``team`` (the franchise abbreviation), and the ``season`` column
carries the requested season. Per-player and per-game fan-out is
silver M3's job; bronze stays uniform with the rest of the M2
ingestion surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import structlog
from pydantic import ValidationError

from puckbunny.ingestion.nhl.endpoints import (
    CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
    ROSTER_ENDPOINT_TEMPLATE,
    club_schedule_season_url,
    format_season_id,
    normalize_team_abbrev,
    roster_url,
    season_start_date,
)
from puckbunny.ingestion.nhl.schemas import (
    ClubScheduleSeasonResponse,
    RosterResponse,
)
from puckbunny.storage.parquet import BronzeEnvelope, write_envelope_partition

if TYPE_CHECKING:
    from datetime import date

    from pydantic import BaseModel

    from puckbunny.http.client import RateLimitedClient
    from puckbunny.storage.base import ObjectStorage
    from puckbunny.storage.parquet import WriteResult

#: Default bronze key prefix. Matches D2 in the M2 plan.
DEFAULT_BRONZE_PREFIX: str = "bronze/nhl_api"

#: Bronze partition names. Hyphenated rather than ``team_season`` /
#: ``club_schedule_season`` so the directory name on disk matches the
#: URL slug — easier to grep across path and URL when debugging.
ROSTER_PARTITION_NAME: str = "roster"
CLUB_SCHEDULE_SEASON_PARTITION_NAME: str = "club-schedule-season"


class ClubScheduleSeasonMismatchError(ValueError):
    """Raised when a club-schedule-season response's ``currentSeason``
    doesn't match the requested ``season``.

    Mirrors :class:`puckbunny.ingestion.nhl.games.GameIdMismatchError`.
    Either case (URL-template bug or upstream redirect) would land
    mismatched payloads in bronze; failing loud here keeps the bronze
    layer trustworthy.
    """


@dataclass(frozen=True)
class TeamSeasonLoadResult:
    """Summary of one :meth:`TeamSeasonLoader.load_one` invocation.

    Each ``WriteResult`` slot is ``None`` when the corresponding
    endpoint returned 404 (typically a ``(team, season)`` pair the
    franchise didn't exist for, e.g. ``UTA`` pre-2024-25). A non-``None``
    value means the fetch succeeded and a bronze row landed.
    """

    season: str
    team: str
    roster: WriteResult | None
    club_schedule_season: WriteResult | None


class TeamSeasonLoader:
    """Fetches roster + club-schedule-season for one ``(season, team)`` pair
    and writes typed envelopes.

    One instance per process is fine; the underlying ``RateLimitedClient``
    holds the shared rate-limit state. Callers must close the client
    themselves (the loader does not own its lifecycle).
    """

    def __init__(
        self,
        client: RateLimitedClient,
        storage: ObjectStorage,
        *,
        base_prefix: str = DEFAULT_BRONZE_PREFIX,
    ) -> None:
        self._client = client
        self._storage = storage
        self._base_prefix = base_prefix
        self._log = structlog.get_logger(__name__)

    def load_one(
        self,
        season: int | str,
        team: str,
        *,
        ingest_date: date | None = None,
    ) -> TeamSeasonLoadResult:
        """Fetch and persist roster + club-schedule-season for
        ``(season, team)``.

        Args:
            season: NHL season identifier in ``YYYYYYYY`` form (e.g.
                ``20242025`` or ``"20242025"``).
            team: 3-letter team abbreviation (e.g. ``"TOR"``,
                ``"UTA"``). Lower- and mixed-case are accepted and
                normalized to upper-case.
            ingest_date: Override for the bronze partition key.
                Defaults to today's UTC date — production ingest should
                leave this unset; backfill scripts may pass a fixed
                value to keep replays in a single partition.

        Returns:
            :class:`TeamSeasonLoadResult` with two ``WriteResult`` slots,
            either of which may be ``None`` on a 404 (log-and-skip).

        Raises:
            ClubScheduleSeasonMismatchError: The
                ``club-schedule-season`` response's ``currentSeason``
                differed from the requested season.
            pydantic.ValidationError: A response failed schema
                validation.
            httpx.HTTPStatusError: Non-404, non-retryable HTTP failure.
            RetryableStatusError: All retries exhausted on 429 / 5xx.
            ValueError: ``season`` or ``team`` is malformed.
        """
        ingest_date = ingest_date or datetime.now(UTC).date()
        # Normalize early so a bad input fails before any I/O. The
        # endpoints helpers raise ValueError on malformed inputs.
        season_str = format_season_id(season)
        team_str = normalize_team_abbrev(team)
        log = self._log.bind(
            season=season_str,
            team=team_str,
            ingest_date=ingest_date.isoformat(),
        )
        log.info("nhl_team_season_load_start")

        roster_write = self._fetch_and_write_or_skip(
            season=season_str,
            team=team_str,
            url=roster_url(team_str, season_str),
            endpoint_template=ROSTER_ENDPOINT_TEMPLATE,
            endpoint_name=ROSTER_PARTITION_NAME,
            schema_cls=RosterResponse,
            ingest_date=ingest_date,
        )
        club_schedule_write = self._fetch_and_write_or_skip(
            season=season_str,
            team=team_str,
            url=club_schedule_season_url(team_str, season_str),
            endpoint_template=CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
            endpoint_name=CLUB_SCHEDULE_SEASON_PARTITION_NAME,
            schema_cls=ClubScheduleSeasonResponse,
            ingest_date=ingest_date,
        )

        log.info(
            "nhl_team_season_load_complete",
            roster_key=roster_write.key if roster_write is not None else None,
            roster_bytes=roster_write.bytes if roster_write is not None else None,
            roster_skipped=roster_write is None,
            club_schedule_key=(
                club_schedule_write.key if club_schedule_write is not None else None
            ),
            club_schedule_bytes=(
                club_schedule_write.bytes if club_schedule_write is not None else None
            ),
            club_schedule_skipped=club_schedule_write is None,
        )
        return TeamSeasonLoadResult(
            season=season_str,
            team=team_str,
            roster=roster_write,
            club_schedule_season=club_schedule_write,
        )

    # --- internals ---

    def _fetch_and_write_or_skip(
        self,
        *,
        season: str,
        team: str,
        url: str,
        endpoint_template: str,
        endpoint_name: str,
        schema_cls: type[BaseModel],
        ingest_date: date,
    ) -> WriteResult | None:
        """Wrap :meth:`_fetch_and_write` with 404 → log-and-skip.

        404 is the spike-confirmed signal for "this ``(team, season)``
        pair didn't exist" (e.g. UTA pre-2024-25). We log a warning so
        the skip is auditable, but don't raise — backfill loops would
        otherwise abort partway through on every franchise edge.
        """
        try:
            return self._fetch_and_write(
                season=season,
                team=team,
                url=url,
                endpoint_template=endpoint_template,
                endpoint_name=endpoint_name,
                schema_cls=schema_cls,
                ingest_date=ingest_date,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                self._log.warning(
                    "nhl_team_season_skipped_404",
                    season=season,
                    team=team,
                    endpoint=endpoint_name,
                    url=url,
                )
                return None
            raise

    def _fetch_and_write(
        self,
        *,
        season: str,
        team: str,
        url: str,
        endpoint_template: str,
        endpoint_name: str,
        schema_cls: type[BaseModel],
        ingest_date: date,
    ) -> WriteResult:
        """Shared fetch → validate → envelope → write path.

        Each endpoint gets its own bronze partition (``endpoint_name``)
        per D2. The body text is kept verbatim — no canonicalization,
        no re-serialization — so ``response_sha256`` is a true digest
        of the API's bytes (same invariant as
        :mod:`puckbunny.ingestion.nhl.games`).

        For ``club-schedule-season``, the parsed response's
        ``currentSeason`` is asserted against the requested ``season``
        as a defensive invariant before bronze is written.
        """
        log = self._log.bind(season=season, team=team, endpoint=endpoint_name)
        log.debug("nhl_team_season_fetch", url=url)

        response = self._client.get(url)
        body_text = response.text

        try:
            parsed = schema_cls.model_validate_json(body_text)
        except ValidationError:
            log.error("nhl_team_season_validation_failed", url=url)
            raise

        # Defensive: club-schedule-season carries currentSeason on the
        # response. If it doesn't match what we asked for, refuse to
        # write — bronze must not silently land mismatched seasons.
        if isinstance(parsed, ClubScheduleSeasonResponse):
            requested_season = int(season)
            if parsed.currentSeason != requested_season:
                raise ClubScheduleSeasonMismatchError(
                    f"requested season={requested_season} but "
                    f"club-schedule-season response reports "
                    f"currentSeason={parsed.currentSeason} "
                    f"(team={team}, URL={url})"
                )

        envelope = BronzeEnvelope(
            entity_id=team,
            endpoint=endpoint_template,
            endpoint_params={"team": team, "season": season},
            fetched_at_utc=datetime.now(UTC),
            response_json=body_text,
            season=season,
            event_date=season_start_date(season),
        )
        return write_envelope_partition(
            self._storage,
            [envelope],
            base_prefix=self._base_prefix,
            endpoint_name=endpoint_name,
            ingest_date=ingest_date,
        )


__all__ = [
    "CLUB_SCHEDULE_SEASON_PARTITION_NAME",
    "DEFAULT_BRONZE_PREFIX",
    "ROSTER_PARTITION_NAME",
    "ClubScheduleSeasonMismatchError",
    "TeamSeasonLoadResult",
    "TeamSeasonLoader",
]
