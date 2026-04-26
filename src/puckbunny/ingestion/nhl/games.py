"""Per-game NHL bronze loader: ``landing`` + ``boxscore`` for one ``gameId``.

This module is the first concrete consumer of the PR-B primitives
(:class:`puckbunny.http.client.RateLimitedClient`,
:class:`puckbunny.storage.parquet.BronzeEnvelope`,
:func:`puckbunny.storage.parquet.write_envelope_partition`). It owns
the choice of *which* fields from the parsed response promote into
the typed envelope columns; every other field rides along in
``response_json``.

Per ``docs/milestones/m2-nhl-ingestion.md`` D2, each endpoint writes
to its own bronze partition (``landing/`` vs ``boxscore/``) so daily
hot-write paths stay separated from cold ones.

The loader exposes a single public method, :meth:`GameLoader.load_one`,
because PR-C is scoped to one game per invocation. PR-G's backfill CLI
will call this in a loop; nothing in this file needs to change for that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from puckbunny.ingestion.nhl.endpoints import (
    BOXSCORE_ENDPOINT_TEMPLATE,
    LANDING_ENDPOINT_TEMPLATE,
    boxscore_url,
    landing_url,
)
from puckbunny.ingestion.nhl.schemas import (
    BoxscoreResponse,
    GameResponseBase,
    LandingResponse,
)
from puckbunny.storage.parquet import BronzeEnvelope, write_envelope_partition

if TYPE_CHECKING:
    from datetime import date

    from puckbunny.http.client import RateLimitedClient
    from puckbunny.storage.base import ObjectStorage
    from puckbunny.storage.parquet import WriteResult

#: Default bronze key prefix. Matches D2 in the M2 plan.
DEFAULT_BRONZE_PREFIX: str = "bronze/nhl_api"


class GameIdMismatchError(ValueError):
    """Raised when the response's ``id`` doesn't match the requested ``game_id``.

    A polite-defaults guard against URL-template bugs in this loader
    or an upstream redirect that swaps the gameId silently. Either
    case would land mismatched payloads in bronze; failing loud here
    keeps the bronze layer trustworthy.
    """


@dataclass(frozen=True)
class GameLoadResult:
    """Summary of one :meth:`GameLoader.load_one` invocation."""

    game_id: int
    landing: WriteResult
    boxscore: WriteResult


class GameLoader:
    """Fetches landing+boxscore for one ``game_id`` and writes typed envelopes.

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
    ) -> GameLoadResult:
        """Fetch and persist landing + boxscore for ``game_id``.

        Args:
            game_id: Canonical NHL game ID (e.g. ``2025030123``).
            ingest_date: Override for the bronze partition key. Defaults
                to today's UTC date — production ingest should leave
                this unset; backfill scripts may pass a fixed value to
                keep replays in a single partition.

        Returns:
            :class:`GameLoadResult` with the two ``WriteResult`` objects.

        Raises:
            GameIdMismatchError: The response's ``id`` differed from
                ``game_id``.
            pydantic.ValidationError: The response failed schema
                validation (missing required field, type mismatch, or
                the spike-§7 game-id-vs-season invariant).
            httpx.HTTPStatusError / RetryableStatusError: The HTTP
                client exhausted retries on a transient/permanent
                failure.
        """
        ingest_date = ingest_date or datetime.now(UTC).date()
        log = self._log.bind(game_id=game_id, ingest_date=ingest_date.isoformat())
        log.info("nhl_games_load_start")

        landing_write = self._fetch_and_write(
            game_id=game_id,
            url=landing_url(game_id),
            endpoint_template=LANDING_ENDPOINT_TEMPLATE,
            endpoint_name="landing",
            schema_cls=LandingResponse,
            ingest_date=ingest_date,
        )
        boxscore_write = self._fetch_and_write(
            game_id=game_id,
            url=boxscore_url(game_id),
            endpoint_template=BOXSCORE_ENDPOINT_TEMPLATE,
            endpoint_name="boxscore",
            schema_cls=BoxscoreResponse,
            ingest_date=ingest_date,
        )

        log.info(
            "nhl_games_load_complete",
            landing_key=landing_write.key,
            landing_bytes=landing_write.bytes,
            boxscore_key=boxscore_write.key,
            boxscore_bytes=boxscore_write.bytes,
        )
        return GameLoadResult(
            game_id=game_id,
            landing=landing_write,
            boxscore=boxscore_write,
        )

    # --- internals ---

    def _fetch_and_write(
        self,
        *,
        game_id: int,
        url: str,
        endpoint_template: str,
        endpoint_name: str,
        schema_cls: type[GameResponseBase],
        ingest_date: date,
    ) -> WriteResult:
        """Shared fetch → validate → envelope → write path.

        Each endpoint gets its own bronze partition (``endpoint_name``)
        per D2. The body text is kept verbatim — no canonicalization,
        no re-serialization — so ``response_sha256`` is a true digest
        of the API's bytes.
        """
        log = self._log.bind(game_id=game_id, endpoint=endpoint_name)
        log.debug("nhl_games_fetch", url=url)

        response = self._client.get(url)
        body_text = response.text

        try:
            parsed = schema_cls.model_validate_json(body_text)
        except ValidationError:
            log.error("nhl_games_validation_failed", url=url)
            raise

        if parsed.id != game_id:
            raise GameIdMismatchError(
                f"requested game_id={game_id} but {endpoint_name} response "
                f"reports id={parsed.id} (URL: {url})"
            )

        envelope = BronzeEnvelope(
            entity_id=str(parsed.id),
            endpoint=endpoint_template,
            endpoint_params={"gameId": game_id},
            fetched_at_utc=datetime.now(UTC),
            response_json=body_text,
            season=str(parsed.season),
            event_date=parsed.gameDate,
        )
        return write_envelope_partition(
            self._storage,
            [envelope],
            base_prefix=self._base_prefix,
            endpoint_name=endpoint_name,
            ingest_date=ingest_date,
        )
