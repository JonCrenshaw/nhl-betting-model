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
from puckbunny.ingestion.nhl.backfill import (
    SUPPORTED_LOADERS,
    BackfillCollaborators,
    BackfillResult,
    run_backfill,
)
from puckbunny.ingestion.nhl.endpoints import parse_season_range, team_abbrevs
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
from puckbunny.ingestion.nhl.team_season import (
    TeamSeasonLoader,
    TeamSeasonLoadResult,
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
    team_season_loader_factory: Callable[
        [argparse.Namespace], tuple[TeamSeasonLoader, Callable[[], None]]
    ]
    | None = None,
    backfill_factory: Callable[
        [argparse.Namespace], tuple[BackfillCollaborators, Callable[[], None]]
    ]
    | None = None,
) -> int:
    """CLI entry point. Returns a process exit code.

    ``loader_factory``, ``pbp_loader_factory``,
    ``daily_loader_factory``, ``season_summaries_loader_factory``,
    ``team_season_loader_factory``, and ``backfill_factory`` are the
    test seams: production callers leave them unset (the defaults
    build R2-backed loaders from :mod:`puckbunny.config`); tests inject
    factories that wire the loaders to a local-filesystem storage + a
    mock HTTP transport. The factories are kept separate per-subcommand
    because each loader produces a different result shape; collapsing
    them into one would add stringly-typed branching for no real win.

    The ``backfill`` subcommand is the exception — it always wires all
    four collaborators (DailyLoader + SeasonSummariesLoader +
    TeamSeasonLoader + ManifestStore) and the
    :class:`BackfillCollaborators` struct holds them as one bundle, so
    the backfill factory returns one struct rather than four
    separately-injectable loaders. Per Q3 of the PR-G planning recap.
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
    if args.command == "team-season":
        return _cmd_team_season(args, team_season_loader_factory=team_season_loader_factory)
    if args.command == "backfill":
        return _cmd_backfill(args, backfill_factory=backfill_factory)

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
            "NHL season identifier. Accepts either YYYYYYYY (e.g. "
            "'20242025') or YYYY-YY (e.g. '2024-25') — both are "
            "normalized to the 8-digit form before the wire call. "
            "Accepts string only; the leading-zero concern doesn't "
            "apply to seasons but ``str`` keeps the CLI shape "
            "predictable across shells."
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

    team_season = sub.add_parser(
        "team-season",
        help=(
            "Fetch roster + club-schedule-season for one (season, team) pair "
            "(or every team in the season if --team omitted) and write to "
            "bronze. Cadence varies by endpoint — see "
            "docs/ideas/team-season-cadence-gating.md for the M10 design."
        ),
    )
    team_season.add_argument(
        "--season",
        type=str,
        required=True,
        help=(
            "NHL season identifier. Accepts either YYYYYYYY (e.g. "
            "'20242025') or YYYY-YY (e.g. '2024-25')."
        ),
    )
    team_season.add_argument(
        "--team",
        type=str,
        default=None,
        help=(
            "3-letter team abbreviation (e.g. 'TOR'). When omitted, "
            "iterates every team valid for --season per "
            "endpoints.team_abbrevs(season)."
        ),
    )
    team_season.add_argument(
        "--ingest-date",
        type=date.fromisoformat,
        default=None,
        help="Override the bronze partition date (YYYY-MM-DD). Defaults to today's UTC date.",
    )
    team_season.add_argument(
        "--log-level",
        default="INFO",
        help="Logging threshold (DEBUG/INFO/WARNING/ERROR). Default INFO.",
    )

    backfill = sub.add_parser(
        "backfill",
        help=(
            "Backfill historical NHL bronze data across a season range. "
            "Composes the team-season + season-summaries + games loaders "
            "with manifest-based per-scope-unit dedupe and an end-of-phase "
            "cost-check tripwire. See docs/milestones/m2-nhl-ingestion.md "
            "PR-G for the design."
        ),
    )
    backfill.add_argument(
        "--from-season",
        type=str,
        required=True,
        help=(
            "First season in the backfill range (inclusive). Accepts "
            "either YYYYYYYY (e.g. '20152016') or YYYY-YY (e.g. "
            "'2015-16')."
        ),
    )
    backfill.add_argument(
        "--to-season",
        type=str,
        required=True,
        help=(
            "Last season in the backfill range (inclusive). Same input "
            "shapes as --from-season. Must be >= --from-season."
        ),
    )
    backfill.add_argument(
        "--loader",
        type=str,
        default="all",
        choices=SUPPORTED_LOADERS,
        help=(
            "Which loader phase(s) to run. 'all' (default) runs "
            "team-season → season-summaries → games in cheap-fail-fast "
            "order. Single-phase values run only that phase."
        ),
    )
    backfill.add_argument(
        "--cost-check",
        type=str,
        default="fail",
        choices=("fail", "warn", "off"),
        help=(
            "Behavior when the end-of-phase cost projection exceeds the "
            "active threshold (default $5/mo, override via "
            "INGEST_COST_CHECK_THRESHOLD_USD). 'fail' (default) raises "
            "to abort before the next phase; 'warn' logs at WARNING and "
            "continues; 'off' skips the threshold action (the "
            "projection is still logged)."
        ),
    )
    backfill.add_argument(
        "--ingest-date",
        type=date.fromisoformat,
        default=None,
        help="Override the bronze partition date (YYYY-MM-DD). Defaults to today's UTC date.",
    )
    backfill.add_argument(
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


def _cmd_team_season(
    args: argparse.Namespace,
    *,
    team_season_loader_factory: Callable[
        [argparse.Namespace], tuple[TeamSeasonLoader, Callable[[], None]]
    ]
    | None,
) -> int:
    """Run :class:`TeamSeasonLoader` for one ``--team`` or every team in
    ``--season`` if ``--team`` is omitted.

    The all-teams branch is the backfill-style invocation; PR-G's
    backfill CLI will compose this same loop with manifest gating,
    but PR-F2 keeps the loop here so manual/debug invocations have a
    single ergonomic entry point.
    """
    configure_logging(level=args.log_level)
    factory = team_season_loader_factory or _default_team_season_loader_factory
    loader, close = factory(args)
    teams: tuple[str, ...] = (
        (args.team,) if args.team is not None else tuple(sorted(team_abbrevs(args.season)))
    )
    results: list[TeamSeasonLoadResult] = []
    try:
        for team in teams:
            results.append(loader.load_one(args.season, team, ingest_date=args.ingest_date))
    finally:
        close()
    _print_team_season_results(args.season, results)
    return 0


def _default_team_season_loader_factory(
    _args: argparse.Namespace,
) -> tuple[TeamSeasonLoader, Callable[[], None]]:
    """Wire production collaborators from environment-driven settings."""
    settings = get_settings()
    storage: ObjectStorage = R2ObjectStorage.from_settings(settings)
    client = RateLimitedClient(
        rate_per_sec=settings.ingest_rate_limit_per_sec,
        user_agent=settings.ingest_user_agent,
        request_timeout_seconds=settings.ingest_request_timeout_seconds,
        max_retries=settings.ingest_max_retries,
    )
    loader = TeamSeasonLoader(client, storage)
    return loader, client.close


def _print_team_season_results(season: str, results: list[TeamSeasonLoadResult]) -> None:
    """Emit a single-line JSON summary for the team-season subcommand.

    Always renders as a list of per-team entries so the shape is the
    same whether the caller passed ``--team`` or iterated all teams.
    Each entry's ``roster`` and ``club_schedule_season`` slots may be
    ``null`` to indicate a 404 log-and-skip.
    """
    teams_summary: list[dict[str, object]] = []
    for r in results:
        entry: dict[str, object] = {"team": r.team}
        if r.roster is not None:
            entry["roster"] = {
                "key": r.roster.key,
                "rows": r.roster.rows,
                "bytes": r.roster.bytes,
            }
        else:
            entry["roster"] = None
        if r.club_schedule_season is not None:
            entry["club_schedule_season"] = {
                "key": r.club_schedule_season.key,
                "rows": r.club_schedule_season.rows,
                "bytes": r.club_schedule_season.bytes,
            }
        else:
            entry["club_schedule_season"] = None
        teams_summary.append(entry)

    summary = {
        "season": season,
        "teams": teams_summary,
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()


def _cmd_backfill(
    args: argparse.Namespace,
    *,
    backfill_factory: Callable[
        [argparse.Namespace], tuple[BackfillCollaborators, Callable[[], None]]
    ]
    | None,
) -> int:
    """Run the historical backfill across ``--from-season`` /
    ``--to-season`` for the requested ``--loader`` phase(s).

    The CLI normalizes the season range here so the orchestrator only
    sees canonical 8-digit ids; bad inputs fail at parse time, before
    any factory-side I/O. Returns ``2`` if the cost-check tripped (per
    Unix convention "non-zero, non-1 = special error"), ``0`` otherwise
    — letting wrapper scripts distinguish "ran clean" from "stopped on
    a budget tripwire" without parsing stdout.
    """
    configure_logging(level=args.log_level)
    seasons = parse_season_range(args.from_season, args.to_season)
    factory = backfill_factory or _default_backfill_factory
    collaborators, close = factory(args)
    try:
        result = run_backfill(
            collaborators,
            seasons=seasons,
            loader=args.loader,
            cost_check_mode=args.cost_check,
            ingest_date=args.ingest_date,
        )
    finally:
        close()
    _print_backfill_result(result)
    return 2 if result.aborted else 0


def _default_backfill_factory(
    _args: argparse.Namespace,
) -> tuple[BackfillCollaborators, Callable[[], None]]:
    """Wire production collaborators: R2 + one shared rate-limited
    client + manifest, with all four loaders constructed against them.

    One client across all four loaders so the rate-limit budget is
    process-wide (per D6) — a backfill run never exceeds the configured
    requests-per-second across phases. The returned ``close`` callable
    closes that one client.
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
    daily_loader = DailyLoader(
        schedule_loader=schedule_loader,
        game_loader=game_loader,
        pbp_loader=pbp_loader,
        manifest=manifest,
    )
    season_summaries_loader = SeasonSummariesLoader(client, storage)
    team_season_loader = TeamSeasonLoader(client, storage)
    collaborators = BackfillCollaborators(
        daily_loader=daily_loader,
        season_summaries_loader=season_summaries_loader,
        team_season_loader=team_season_loader,
        manifest=manifest,
    )
    return collaborators, client.close


def _print_backfill_result(result: BackfillResult) -> None:
    """Emit a single-line JSON summary for the ``backfill`` subcommand.

    Per-phase counts make the run auditable at a glance; the manifest
    is the source of truth for what landed where, but operators
    typically want "did the run abort, and roughly how much did each
    phase do" before drilling into the JSONL.
    """
    phases_summary: list[dict[str, object]] = [
        {
            "phase": p.phase,
            "scope_units_attempted": p.scope_units_attempted,
            "scope_units_skipped": p.scope_units_skipped,
            "scope_units_loaded": p.scope_units_loaded,
            "manifest_entries_appended": p.manifest_entries_appended,
        }
        for p in result.phase_results
    ]
    summary: dict[str, object] = {
        "run_id": result.run_id,
        "loader": result.loader,
        "cost_check_mode": result.cost_check_mode,
        "ingest_date": result.ingest_date.isoformat(),
        "seasons": result.seasons,
        "phases": phases_summary,
        "aborted": result.aborted,
    }
    if result.aborted:
        summary["aborted_reason"] = result.aborted_reason
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()
