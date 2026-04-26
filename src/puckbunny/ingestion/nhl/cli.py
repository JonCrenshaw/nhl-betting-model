"""``python -m puckbunny.ingestion.nhl ...`` command-line entry point.

PR-C ships one subcommand: ``games --game-id <id>``. PR-D adds
``play-by-play``; PR-E adds ``daily``; PR-G adds ``backfill``. The
shell uses ``argparse`` rather than a third-party CLI framework — the
surface is small, the dep cost is zero, and the behavior is
predictable across shells.

The CLI is intentionally thin: parse args, build the wired-up
collaborators (settings → R2 storage → rate-limited client →
loader), invoke the loader, print a one-line summary on success.
Tests exercise :func:`main` directly with ``argv`` and a stub
loader factory; see ``tests/ingestion/test_nhl_games.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import TYPE_CHECKING

from puckbunny.config import get_settings
from puckbunny.http.client import RateLimitedClient
from puckbunny.ingestion.nhl.games import GameLoader, GameLoadResult
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
) -> int:
    """CLI entry point. Returns a process exit code.

    ``loader_factory`` is the test seam: production callers leave it
    unset (the default builds an R2-backed loader from
    :mod:`puckbunny.config`); tests inject a factory that wires the
    loader to a local-filesystem storage + a mock HTTP transport.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "games":
        return _cmd_games(args, loader_factory=loader_factory)

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
