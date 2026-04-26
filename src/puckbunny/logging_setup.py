"""Configure structured logging for PuckBunny.

The single entry point :func:`configure_logging` sets up both stdlib
``logging`` and ``structlog`` to emit one record per line. JSON is the
default in non-TTY environments (CI, prod, redirected output); a
human-readable console renderer is used in interactive shells. The
function is idempotent, so calling it more than once per process is
harmless.

Production code should obtain loggers via ``structlog.get_logger(__name__)``
and never use ``print``.
"""

from __future__ import annotations

import logging
import sys
from typing import Final

import structlog

_CONFIGURED: bool = False
_DEFAULT_LEVEL: Final[str] = "INFO"


def configure_logging(
    *,
    level: str | int = _DEFAULT_LEVEL,
    json_output: bool | None = None,
    force: bool = False,
) -> None:
    """Configure stdlib ``logging`` and ``structlog`` for the process.

    Args:
        level: Threshold for both loggers. Accepts a name (``"INFO"``) or
            a numeric level.
        json_output: ``True`` emits JSON; ``False`` uses the dev console
            renderer; ``None`` (default) auto-detects from ``sys.stderr``
            being a TTY.
        force: Re-run configuration even if already configured. Useful
            in tests that need to switch renderers.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level_value = _resolve_level(level)
    use_json = (not sys.stderr.isatty()) if json_output is None else json_output

    # Stdlib logging: emit raw messages on stdout. structlog formats them
    # before they reach the handler, so we avoid the default "%(asctime)s
    # %(levelname)s %(message)s" formatting layered on top.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level_value,
        force=True,
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if use_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_value),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def _resolve_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    mapping = logging.getLevelNamesMapping()
    return mapping.get(level.upper(), logging.INFO)
