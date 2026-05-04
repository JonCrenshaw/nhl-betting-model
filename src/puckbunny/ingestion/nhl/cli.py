"""``python -m puckbunny.ingestion.nhl ...`` command-line entry point.

PR-C shipped ``games --game-id <id>``. PR-D added
``play-by-play --game-id <id>``. PR-E adds ``daily [--date YYYY-MM-DD]``;
PR-G adds ``backfill``. The shell uses ``argparse`` rather than a
third-party CLI framework — the surface is small, the dep cost is
zero, and the behavior is predictable across shells.

The CLI is intentionally thin: parse args, build the wired-up
collaborators (settings → R2 storage → rate-limited client →
loader), invoke the loader, print a one-line summary on success.
Tests exercise :func:`main` directly with ``argv`` and a stub
loader factory; see ``tests/ingestion/test_nhl_games.py``,
``tests/ingestion/test_nhl_pbp.py``, and
``tests/ingestion/test_schedule.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import TYPE_CHECKING

from puckbunny.config import get_settings
from puckbunny.http.client import RateLimitedClient
from puckbunny.ingestion.manifest import ManifestStore
from puckbunny.ingestion.nhl.games import GameLoader, GameLoadResult
from puckbunny.ingestion.nhl.play_by_play import (
    PlayByPlayLoader,
    PlayByPlayLoadResult,
)
from puckbunny.ingestion.nhl.schedule import (
    DailyLoader,
    DailyLoadResult,
    ScheduleLoader,
    yesterday_in_toronto,
)
from puckbunny.ingestion.nhl.season_summaries import (
    SeasonSummariesLoader,
    SeasonSummariesLoadResult,
)
from puckbunny.logging_setup import configure_logging
from puckbunny.storage.r2 import R2ObjectStorage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from puckbunny.storage.base import ObjectStorage

# The loader factory is the test seam: tests substitute one that
# returns a :class:`GameLoader` wired to ``LocalFilesystemStorage`` +
# an :class:`httpx.MockTransport`-backed client, so ``main`` runs end
# to end without touching R2 or the live API. The signature is
# expressed inline at each use site rather than via a type alias —
# pydantic-style alias declarations don't survive ``from __future__
# import annotations`` cleanly without ``TypeAlias``, and the inline
# form reads fine.


def main(
    argv: Sequence[str] | None = None,
    *,
    loader_factory: Callable[[argparse.Namespace], tuple[GameLoader, Callable[[], None]]]
    | None = None,
    pbp_loader_factory: Callable[[argparse.Namespace], tuple[PlayByPlayLoader, Callable[[], None]]]
    | None = None,
    daily_loader_factory: Callable[[argparse.Namespace], tuple[DailyLoader, Callable[[], None]]]
    | None = None,
    season_summaries_loader_factory: Callable[
        [argparse.Namespace], tuple[SeasonSummariesLoader, Callable[[], None]]
    ]
    | None = None,
) -> int:
    """CLI entry point. Returns a process exit code.

    ``loader_factory``, ``pbp_loader_factory``,
    ``daily_loader_factory``, and ``season_summaries_loader_factory``
    are the test seams: production callers leave them unset (the
    defaults build R2-backed loaders from :mod:`puckbunny.config`);
    tests inject factories that wire the loader to a local-filesystem
    storage + a mock HTTP transport. The factories are kept separate
    because the loaders produce different result shapes; collapsing
    them into one would add stringly-typed branching for no real win.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "games":
        return _cmd_games(args, loader_factory=loader_factory)
    if args.command == "play-by-play":
        return _cmd_play_by_play(args, pbp_loader_factory=pbp_loader_factory)
    if args.command == "daily":
        return _cmd_daily(args, daily_loader_factory=daily_loader_factory)
    if args.command == "season-summaries":
        return _cmd_season_summaries(
            args, season_summaries_loader_factory=season_summaries_loader_factory
        )

    # argparse should already have errored on an unknown command via
    # ``required=True`` on the subparsers; this is defense in depth.
    parser.error(f"unknown command: {args.command!r}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m puckbunny.ingestion.nhl",
        description="PuckBunny NHL bronze ingestion CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    games = sub.add_parser(
        "games",
        help="Fetch landing+boxscore for one game id and write to bronze.",
    )
    games.add_argument(
        "--game-id",
        type=int,
        required=True,
        help="Canonical NHL game ID, e.g. 2025030123.",
    )
    games.add_argument(
        "--ingest-date",
        type=date.fromisoformat,
        default=None,
        help="Override the bronze partition date (YYYY-MM-DD). Defaults to today's UTC date.",
    )
    games.add_argument(
        "--log-level",
        default="INFO",
        help="Logging threshold (DEBUG/INFO/WARNING/ERROR). Default INFO.",
    )

    pbp = sub.add_parser(
        "play-by-play",
        help="Fetch play-by-play for one game id and write to bronze.",
    )
    pbp.add_argument(
        "--game-id",
        type=int,
        required=True,
        help="Canonical NHL game ID, e.g. 2025030123.",
    )
    pbp.add_argument(
        "--ingest-date",
        type=date.fromisoformat,
        default=None,
        help="Override the bronze partition date (YYYY-MM-DD). Defaults to today's UTC date.",
    )
    pbp.add_argument(
        "--log-level",
        default="INFO",
        help="Logging threshold (DEBUG/INFO/WARNING/ERROR). Default INFO.",
    )

    daily = sub.add_parser(
        "daily",
        help=(
            "Walk one day's NHL schedule and ingest landing+boxscore+play-by-play "
            "for every FINAL/OFF game not already in the manifest."
        ),
    )
    daily.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help=(
            "NHL gameDate to ingest (YYYY-MM-DD). Defaults to yesterday in "
            "America/Toronto so a morning UTC run picks up the previous slate."
        ),
    )
    daily.add_argument(
        "--ingest-date",
        type=date.fromisoformat,
        default=None,
        help="Override the bronze partition date (YYYY-MM-DD). Defaults to today's UTC date.",
    )
    daily.add_argument(
        "--log-level",
        default="INFO",
        help="Logging threshold (DEBUG/INFO/WARNING/ERROR). Default INFO.",
    )

    season_summaries = sub.add_parser(
        "season-summaries",
        help=(
            "Fetch skater+goalie+team season summaries for one season "
            "and write to bronze. Cadence is weekly + post-Stanley-Cup-Final, "
            "NOT daily — see season_summaries.py module docstring."
        ),
    )
    season_summaries.add_argument(
        "--season",
        type=str,
        required=True,
        help=(
            "NHL season identifier in YYYYYYYY form (e.g. '20242025' for "
            "the 2024-25 season). Accepts string only — the leading-zero "
            "concern doesn't apply to seasons but ``str`` keeps the CLI "
            "shape predictable across shells."
        ),
    )
    season_summaries.add_argument(
        "--ingest-date",
        type=date.fromisoformat,
        default=None,
        help="Override the bronze partition date (YYYY-MM-DD). Defaults to today's UTC date.",
    )
    season_summaries.add_argument(
        "--log-level",
        default="INFO",
        help="Logging threshold (DEBUG/INFO/WARNING/ERROR). Default INFO.",
    )

    return parser


def _cmd_games(
    args: argparse.Namespace,
    *,
    loader_factory: Callable[[argparse.Namespace], tuple[GameLoader, Callable[[], None]]] | None,
) -> int:
    configure_logging(level=args.log_level)
    factory = loader_factory or _default_loader_factory
    loader, close = factory(args)
    try:
        result = loader.load_one(args.game_id, ingest_date=args.ingest_date)
    finally:
        close()
    _print_result(result)
    return 0


def _default_loader_factory(
    _args: argparse.Namespace,
) -> tuple[GameLoader, Callable[[], None]]:
    """Wire production collaborators from environment-driven settings."""
    settings = get_settings()
    storage: ObjectStorage = R2ObjectStorage.from_settings(settings)
    client = RateLimitedClient(
        rate_per_sec=settings.ingest_rate_limit_per_sec,
        user_agent=settings.ingest_user_agent,
        request_timeout_seconds=settings.ingest_request_timeout_seconds,
        max_retries=settings.ingest_max_retries,
    )
    loader = GameLoader(client, storage)
    return loader, client.close


def _cmd_play_by_play(
    args: argparse.Namespace,
    *,
    pbp_loader_factory: Callable[[argparse.Namespace], tuple[PlayByPlayLoader, Callable[[], None]]]
    | None,
) -> int:
    configure_logging(level=args.log_level)
    factory = pbp_loader_factory or _default_pbp_loader_factory
    loader, close = factory(args)
    try:
        result = loader.load_one(args.game_id, ingest_date=args.ingest_date)
    finally:
        close()
    _print_pbp_result(result)
    return 0


def _default_pbp_loader_factory(
    _args: argparse.Namespace,
) -> tuple[PlayByPlayLoader, Callable[[], None]]:
    """Wire production collaborators from environment-driven settings."""
    settings = get_settings()
    storage: ObjectStorage = R2ObjectStorage.from_settings(settings)
    client = RateLimitedClient(
        rate_per_sec=settings.ingest_rate_limit_per_sec,
        user_agent=settings.ingest_user_agent,
        request_timeout_seconds=settings.ingest_request_timeout_seconds,
        max_retries=settings.ingest_max_retries,
    )
    loader = PlayByPlayLoader(client, storage)
    return loader, client.close


def _print_result(result: GameLoadResult) -> None:
    """Emit a single-line JSON summary to stdout for shell composition."""
    summary = {
        "game_id": result.game_id,
        "landing": {
            "key": result.landing.key,
            "rows": result.landing.rows,
            "bytes": result.landing.bytes,
        },
        "boxscore": {
            "key": result.boxscore.key,
            "rows": result.boxscore.rows,
            "bytes": result.boxscore.bytes,
        },
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()


def _print_pbp_result(result: PlayByPlayLoadResult) -> None:
    """Emit a single-line JSON summary for the play-by-play subcommand."""
    summary = {
        "game_id": result.game_id,
        "play_by_play": {
            "key": result.play_by_play.key,
            "rows": result.play_by_play.rows,
            "bytes": result.play_by_play.bytes,
        },
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()


def _cmd_daily(
    args: argparse.Namespace,
    *,
    daily_loader_factory: Callable[[argparse.Namespace], tuple[DailyLoader, Callable[[], None]]]
    | None,
) -> int:
    configure_logging(level=args.log_level)
    target_date: date = args.date if args.date is not None else yesterday_in_toronto()
    factory = daily_loader_factory or _default_daily_loader_factory
    loader, close = factory(args)
    try:
        result = loader.load_date(target_date, ingest_date=args.ingest_date)
    finally:
        close()
    _print_daily_result(result)
    return 0


def _default_daily_loader_factory(
    _args: argparse.Namespace,
) -> tuple[DailyLoader, Callable[[], None]]:
    """Wire production collaborators: R2 + rate-limited client + manifest.

    The same client backs the schedule, games, and PxP loaders so the
    rate-limit budget is shared (one process = one budget). The
    manifest also lives in R2 alongside the bronze data so a fresh
    machine inherits idempotency state from the bucket without any
    local cache.
    """
    settings = get_settings()
    storage: ObjectStorage = R2ObjectStorage.from_settings(settings)
    client = RateLimitedClient(
        rate_per_sec=settings.ingest_rate_limit_per_sec,
        user_agent=settings.ingest_user_agent,
        request_timeout_seconds=settings.ingest_request_timeout_seconds,
        max_retries=settings.ingest_max_retries,
    )
    schedule_loader = ScheduleLoader(client)
    game_loader = GameLoader(client, storage)
    pbp_loader = PlayByPlayLoader(client, storage)
    manifest = ManifestStore(storage)
    daily = DailyLoader(
        schedule_loader=schedule_loader,
        game_loader=game_loader,
        pbp_loader=pbp_loader,
        manifest=manifest,
    )
    return daily, client.close


def _print_daily_result(result: DailyLoadResult) -> None:
    """Emit a single-line JSON summary for the ``daily`` subcommand.

    Per-game keys are kept compact: the goal is "is this run healthy
    at a glance," not full reproducibility (the manifest covers that).
    """
    games_summary = []
    for outcome in result.outcomes:
        if outcome.skipped:
            games_summary.append({"game_id": outcome.game_id, "skipped": True})
            continue
        # Non-skipped means all three writes happened — assert in
        # debug builds, but tolerate in production rather than crash
        # the summary printer over a missing field.
        entry: dict[str, object] = {"game_id": outcome.game_id, "skipped": False}
        if outcome.landing is not None:
            entry["landing_key"] = outcome.landing.key
        if outcome.boxscore is not None:
            entry["boxscore_key"] = outcome.boxscore.key
        if outcome.play_by_play is not None:
            entry["play_by_play_key"] = outcome.play_by_play.key
        games_summary.append(entry)

    summary = {
        "target_date": result.target_date.isoformat(),
        "ingest_date": result.ingest_date.isoformat(),
        "run_id": result.run_id,
        "games_in_schedule": result.games_in_schedule,
        "games_eligible": result.games_eligible,
        "games_loaded": result.games_loaded,
        "games_skipped": result.games_skipped,
        "games": games_summary,
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()


def _cmd_season_summaries(
    args: argparse.Namespace,
    *,
    season_summaries_loader_factory: Callable[
        [argparse.Namespace], tuple[SeasonSummariesLoader, Callable[[], None]]
    ]
    | None,
) -> int:
    configure_logging(level=args.log_level)
    factory = season_summaries_loader_factory or _default_season_summaries_loader_factory
    loader, close = factory(args)
    try:
        result = loader.load_one(args.season, ingest_date=args.ingest_date)
    finally:
        close()
    _print_season_summaries_result(result)
    return 0


def _default_season_summaries_loader_factory(
    _args: argparse.Namespace,
) -> tuple[SeasonSummariesLoader, Callable[[], None]]:
    """Wire production collaborators from environment-driven settings."""
    settings = get_settings()
    storage: ObjectStorage = R2ObjectStorage.from_settings(settings)
    client = RateLimitedClient(
        rate_per_sec=settings.ingest_rate_limit_per_sec,
        user_agent=settings.ingest_user_agent,
        request_timeout_seconds=settings.ingest_request_timeout_seconds,
        max_retries=settings.ingest_max_retries,
    )
    loader = SeasonSummariesLoader(client, storage)
    return loader, client.close


def _print_season_summaries_result(result: SeasonSummariesLoadResult) -> None:
    """Emit a single-line JSON summary for the season-summaries subcommand."""
    summary = {
        "season": result.season,
        "skater_summary": {
            "key": result.skater_summary.key,
            "rows": result.skater_summary.rows,
            "bytes": result.skater_summary.bytes,
        },
        "goalie_summary": {
            "key": result.goalie_summary.key,
            "rows": result.goalie_summary.rows,
            "bytes": result.goalie_summary.bytes,
        },
        "team_summary": {
            "key": result.team_summary.key,
            "rows": result.team_summary.rows,
            "bytes": result.team_summary.bytes,
        },
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()
