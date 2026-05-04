"""Per-season NHL bronze loader: ``skater`` + ``goalie`` + ``team``
season summaries from the ``api.nhle.com/stats/rest/en`` surface.

Sister to :mod:`puckbunny.ingestion.nhl.games` and
:mod:`puckbunny.ingestion.nhl.play_by_play` — same PR-B primitives
(rate-limited HTTP + typed envelope + bronze partition writer), same
"one fetch = one envelope row" bronze invariant, but on a different
host and different versioning convention. See
:mod:`puckbunny.ingestion.nhl.endpoints` for the host/path differences.

Cadence note (per PR-F0 spike §6 + the M2 milestone doc PR-F1
description). Season summaries change slowly relative to game-level
endpoints — daily ingest would be mostly a no-op during the regular
season and stale-by-construction mid-playoffs. **This loader is not
wired into the daily walker built in PR-E.** M10's Dagster schedule
will run it weekly during the season plus a one-shot post-Stanley-Cup
pull to capture finalized totals; until then PR-G's backfill CLI is
the only caller.

Manifest gating note (parked for M10 in
``docs/ideas/season-summaries-cadence-gating.md``). The loader is
intentionally cadence-agnostic — it always fetches when called, and
records the manifest entry unconditionally. The "should we skip
because we already have this?" question is answered by the *caller*
(PR-G backfill or M10's Dagster asset), not by this loader. Backfill
gates via ``manifest.has(endpoint, season)``; the weekly maintenance
schedule deliberately bypasses gating so each week produces a fresh
bronze snapshot. See the parked idea file for the full rationale and
the alternative considered.

Note that the daily walker DOES feed Elo and any prediction model
keyed off per-game results — that pipeline is fresh next-morning UTC
via PR-E. The weekly bronze snapshots written by this loader are not
the freshness-sensitive path; they exist for cross-checking silver
aggregates against NHL's authoritative numbers, capturing
NHL-derived stats we don't easily reconstruct, and preserving
intra-season time-series for backtest reproducibility.

GameTypeId tradeoff (per PR-F0 spike §5). The unfiltered response
combines regular + playoff aggregates for finalized seasons. PR-F1
ships the cheapest path — fetch unfiltered, accept combined; silver
M3 either uses the combined-aggregate as a season prior or asks for
the medium path (two fetches per season with explicit
``gameTypeId={2,3}`` filters and ``scope_key`` extended). The
decision and revisit trigger live in ADR-0003 (PR-H); this loader's
behavior is the V1 default until that ADR explicitly changes it.

Bronze row granularity (per the PR-F1 design discussion). Like
PR-C/D/E this loader writes **one envelope row per fetch** — the
verbatim ``{"data": [...], "total": N}`` body lands in
``response_json``, and ``entity_id`` is ``str(seasonId)``. The
"natural key is weak for season-scoped rows" tradeoff is deliberate:
preserving the verbatim ``response_sha256`` invariant and the 1:1
manifest↔bronze cardinality matters more than per-player queryability
in bronze, which is silver M3's job anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from puckbunny.ingestion.nhl.endpoints import (
    GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
    SKATER_SUMMARY_ENDPOINT_TEMPLATE,
    TEAM_SUMMARY_ENDPOINT_TEMPLATE,
    goalie_summary_url,
    season_start_date,
    season_summary_query_params,
    skater_summary_url,
    team_summary_url,
)
from puckbunny.ingestion.nhl.schemas import (
    GoalieSummaryResponse,
    SkaterSummaryResponse,
    TeamSummaryResponse,
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

#: Bronze partition names. Hyphenated rather than ``skater_summary``
#: so the directory name on disk matches the URL slug — easier to grep
#: across path and URL when debugging.
SKATER_SUMMARY_PARTITION_NAME: str = "skater-summary"
GOALIE_SUMMARY_PARTITION_NAME: str = "goalie-summary"
TEAM_SUMMARY_PARTITION_NAME: str = "team-summary"


@dataclass(frozen=True)
class SeasonSummariesLoadResult:
    """Summary of one :meth:`SeasonSummariesLoader.load_one` invocation.

    Each field is the :class:`WriteResult` from one of the three
    endpoints. Mirrors :class:`puckbunny.ingestion.nhl.games.GameLoadResult`
    in shape — one ``WriteResult`` per endpoint that was fetched.
    """

    season: str
    skater_summary: WriteResult
    goalie_summary: WriteResult
    team_summary: WriteResult


class SeasonSummariesLoader:
    """Fetches the three season-summary endpoints for one ``season`` and
    writes typed envelopes.

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
        *,
        ingest_date: date | None = None,
    ) -> SeasonSummariesLoadResult:
        """Fetch and persist all three season-summary endpoints for
        ``season``.

        Args:
            season: NHL season identifier in ``YYYYYYYY`` form (e.g.
                ``20242025`` or ``"20242025"``).
            ingest_date: Override for the bronze partition key.
                Defaults to today's UTC date — production ingest should
                leave this unset; backfill scripts may pass a fixed
                value to keep replays in a single partition.

        Returns:
            :class:`SeasonSummariesLoadResult` with three
            ``WriteResult`` objects (one per endpoint).

        Raises:
            pydantic.ValidationError: A response failed schema
                validation, including the
                ``len(data) == total`` envelope invariant.
            httpx.HTTPStatusError / RetryableStatusError: The HTTP
                client exhausted retries on a transient/permanent
                failure.
            ValueError: ``season`` is not an 8-digit string/int.
        """
        ingest_date = ingest_date or datetime.now(UTC).date()
        # Normalize early — also validates the format and raises with a
        # helpful message before any I/O.
        season_str = str(season)
        log = self._log.bind(season=season_str, ingest_date=ingest_date.isoformat())
        log.info("nhl_season_summaries_load_start")

        skater_write = self._fetch_and_write(
            season=season_str,
            url=skater_summary_url(season_str),
            endpoint_template=SKATER_SUMMARY_ENDPOINT_TEMPLATE,
            endpoint_name=SKATER_SUMMARY_PARTITION_NAME,
            schema_cls=SkaterSummaryResponse,
            ingest_date=ingest_date,
        )
        goalie_write = self._fetch_and_write(
            season=season_str,
            url=goalie_summary_url(season_str),
            endpoint_template=GOALIE_SUMMARY_ENDPOINT_TEMPLATE,
            endpoint_name=GOALIE_SUMMARY_PARTITION_NAME,
            schema_cls=GoalieSummaryResponse,
            ingest_date=ingest_date,
        )
        team_write = self._fetch_and_write(
            season=season_str,
            url=team_summary_url(season_str),
            endpoint_template=TEAM_SUMMARY_ENDPOINT_TEMPLATE,
            endpoint_name=TEAM_SUMMARY_PARTITION_NAME,
            schema_cls=TeamSummaryResponse,
            ingest_date=ingest_date,
        )

        log.info(
            "nhl_season_summaries_load_complete",
            skater_key=skater_write.key,
            skater_bytes=skater_write.bytes,
            goalie_key=goalie_write.key,
            goalie_bytes=goalie_write.bytes,
            team_key=team_write.key,
            team_bytes=team_write.bytes,
        )
        return SeasonSummariesLoadResult(
            season=season_str,
            skater_summary=skater_write,
            goalie_summary=goalie_write,
            team_summary=team_write,
        )

    # --- internals ---

    def _fetch_and_write(
        self,
        *,
        season: str,
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

        The ``len(data) == total`` envelope invariant is enforced by
        the pydantic schema's post-validator; a violation raises
        :class:`pydantic.ValidationError` here, before bronze gets
        written.
        """
        log = self._log.bind(season=season, endpoint=endpoint_name)
        params = season_summary_query_params(season)
        log.debug("nhl_season_summaries_fetch", url=url, params=params)

        response = self._client.get(url, params=params)
        body_text = response.text

        try:
            schema_cls.model_validate_json(body_text)
        except ValidationError:
            log.error("nhl_season_summaries_validation_failed", url=url)
            raise

        envelope = BronzeEnvelope(
            entity_id=season,
            endpoint=endpoint_template,
            endpoint_params=params,
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
    "DEFAULT_BRONZE_PREFIX",
    "GOALIE_SUMMARY_PARTITION_NAME",
    "SKATER_SUMMARY_PARTITION_NAME",
    "TEAM_SUMMARY_PARTITION_NAME",
    "SeasonSummariesLoadResult",
    "SeasonSummariesLoader",
]
