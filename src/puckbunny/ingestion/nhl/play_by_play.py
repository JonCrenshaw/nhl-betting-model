"""Per-game NHL bronze loader: ``play-by-play`` for one ``gameId``.

PxP is the largest per-game payload (the PR-A spike measured ~131 KB
JSON / ~16 KB Parquet, vs ~14 KB / ~6 KB for landing/boxscore). It's
also the only game-level endpoint that carries ``rosterSpots`` (per
spike notes §3) and the event-level ``plays`` array. Both are pinned
on :class:`puckbunny.ingestion.nhl.schemas.PlayByPlayResponse`.

This loader is structurally parallel to
:class:`puckbunny.ingestion.nhl.games.GameLoader` and uses the same
PR-B primitives (rate-limited HTTP + typed envelope + bronze partition
writer). Kept as its own module rather than added to ``games.py``
because PxP has different scaling characteristics (8x larger
payloads, slower-evolving silver consumers) and the M2 plan calls for
its own bronze partition (``play-by-play/`` per D2).

PR-G's backfill CLI will call :meth:`PlayByPlayLoader.load_one` in a
loop alongside the games loader.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from puckbunny.ingestion.nhl.endpoints import (
    PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
    play_by_play_url,
)
from puckbunny.ingestion.nhl.schemas import PlayByPlayResponse
from puckbunny.storage.parquet import BronzeEnvelope, write_envelope_partition

if TYPE_CHECKING:
    from datetime import date

    from puckbunny.http.client import RateLimitedClient
    from puckbunny.storage.base import ObjectStorage
    from puckbunny.storage.parquet import WriteResult

#: Default bronze key prefix. Matches D2 in the M2 plan.
DEFAULT_BRONZE_PREFIX: str = "bronze/nhl_api"

#: Bronze partition name for the play-by-play endpoint. Hyphenated
#: rather than ``play_by_play`` so the directory name on disk matches
#: the URL slug — easier to grep across path and URL when debugging.
PLAY_BY_PLAY_PARTITION_NAME: str = "play-by-play"


class GameIdMismatchError(ValueError):
    """Raised when the response's ``id`` doesn't match the requested ``game_id``.

    Same guard as :class:`puckbunny.ingestion.nhl.games.GameIdMismatchError`,
    duplicated rather than imported because the two loaders are
    independently invokable and we'd rather not couple their failure
    modes through a shared exception module yet. Consolidate in PR-G
    if the duplication starts to itch.
    """


@dataclass(frozen=True)
class PlayByPlayLoadResult:
    """Summary of one :meth:`PlayByPlayLoader.load_one` invocation."""

    game_id: int
    play_by_play: WriteResult


class PlayByPlayLoader:
    """Fetches play-by-play for one ``game_id`` and writes a typed envelope.

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
        game_id: int,
        *,
        ingest_date: date | None = None,
    ) -> PlayByPlayLoadResult:
        """Fetch and persist play-by-play for ``game_id``.

        Args:
            game_id: Canonical NHL game ID (e.g. ``2025030123``).
            ingest_date: Override for the bronze partition key. Defaults
                to today's UTC date — production ingest should leave
                this unset; backfill scripts may pass a fixed value to
                keep replays in a single partition.

        Returns:
            :class:`PlayByPlayLoadResult` with the underlying
            ``WriteResult``.

        Raises:
            GameIdMismatchError: The response's ``id`` differed from
                ``game_id``.
            pydantic.ValidationError: The response failed schema
                validation (missing ``plays``/``rosterSpots``, type
                mismatch, or the spike-§7 game-id-vs-season invariant
                inherited from :class:`GameResponseBase`).
            httpx.HTTPStatusError / RetryableStatusError: The HTTP
                client exhausted retries on a transient/permanent
                failure.
        """
        ingest_date = ingest_date or datetime.now(UTC).date()
        log = self._log.bind(game_id=game_id, ingest_date=ingest_date.isoformat())
        log.info("nhl_pbp_load_start")

        url = play_by_play_url(game_id)
        log.debug("nhl_pbp_fetch", url=url)

        response = self._client.get(url)
        body_text = response.text

        try:
            parsed = PlayByPlayResponse.model_validate_json(body_text)
        except ValidationError:
            log.error("nhl_pbp_validation_failed", url=url)
            raise

        if parsed.id != game_id:
            raise GameIdMismatchError(
                f"requested game_id={game_id} but play-by-play response "
                f"reports id={parsed.id} (URL: {url})"
            )

        envelope = BronzeEnvelope(
            entity_id=str(parsed.id),
            endpoint=PLAY_BY_PLAY_ENDPOINT_TEMPLATE,
            endpoint_params={"gameId": game_id},
            fetched_at_utc=datetime.now(UTC),
            response_json=body_text,
            season=str(parsed.season),
            event_date=parsed.gameDate,
        )
        write_result = write_envelope_partition(
            self._storage,
            [envelope],
            base_prefix=self._base_prefix,
            endpoint_name=PLAY_BY_PLAY_PARTITION_NAME,
            ingest_date=ingest_date,
        )

        log.info(
            "nhl_pbp_load_complete",
            key=write_result.key,
            bytes=write_result.bytes,
            plays=len(parsed.plays),
            roster_spots=len(parsed.rosterSpots),
        )
        return PlayByPlayLoadResult(game_id=game_id, play_by_play=write_result)
