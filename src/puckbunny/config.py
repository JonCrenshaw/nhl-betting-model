"""Application configuration via ``pydantic-settings``.

Values are sourced from process environment variables first, then from a
``.env`` file in the repository root if present. Tests should either
construct ``Settings(...)`` with explicit kwargs or use ``monkeypatch`` to
set environment variables; do not rely on the ambient ``.env`` in test
code.

See ``.env.example`` for the canonical key list and
``docs/milestones/m2-nhl-ingestion.md`` for the rationale behind each
default.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the repo-root .env at import time so that ``Settings()`` "just
# works" from any cwd. Tests can override by passing ``_env_file=`` kwargs.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Process-wide PuckBunny settings.

    R2 credentials are required. Ingestion knobs have safe defaults that
    match the M2 plan and the PR-A spike's measurements.
    """

    model_config = SettingsConfigDict(
        env_file=str(_DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        # Tolerate forward-compat keys silently rather than blowing up
        # CI when a future PR adds a new variable to .env.example.
        extra="ignore",
        case_sensitive=False,
    )

    # ----- Cloudflare R2 (S3-compatible) -----
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_endpoint_url: str
    r2_bucket: str
    r2_region: str = "auto"

    # ----- Ingestion defaults (overridable per-invocation) -----
    ingest_rate_limit_per_sec: float = Field(default=2.0, gt=0.0, le=100.0)
    ingest_user_agent: str = "PuckBunny/0.1 (contact: crenshaw.jonathan@gmail.com)"
    ingest_request_timeout_seconds: float = Field(default=60.0, gt=0.0, le=600.0)
    ingest_max_retries: int = Field(default=5, ge=0, le=20)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance.

    Cached so the .env file is parsed exactly once per process. Tests
    that construct alternate settings should call ``Settings(...)``
    directly rather than going through this helper.
    """
    return Settings()  # type: ignore[call-arg]
