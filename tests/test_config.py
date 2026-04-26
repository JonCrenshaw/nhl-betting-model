"""Tests for ``puckbunny.config``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from puckbunny.config import Settings, get_settings

if TYPE_CHECKING:
    from pathlib import Path

_REQUIRED_R2_ENV = {
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "ak",
    "R2_SECRET_ACCESS_KEY": "sk",
    "R2_ENDPOINT_URL": "https://acct.r2.cloudflarestorage.com",
    "R2_BUCKET": "puckbunny-lake",
}


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k, v in _REQUIRED_R2_ENV.items():
        monkeypatch.setenv(k, v)
    # Point at a non-existent env file so monkeypatched env wins cleanly.
    settings = Settings(_env_file=str(tmp_path / "nope.env"))  # type: ignore[call-arg]

    assert settings.r2_account_id == "acct"
    assert settings.r2_bucket == "puckbunny-lake"
    # Defaults applied.
    assert settings.r2_region == "auto"
    assert settings.ingest_rate_limit_per_sec == 2.0
    assert settings.ingest_request_timeout_seconds == 60.0
    assert settings.ingest_max_retries == 5
    assert "PuckBunny" in settings.ingest_user_agent


def test_missing_required_field_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Set everything except R2_BUCKET.
    for k, v in _REQUIRED_R2_ENV.items():
        if k == "R2_BUCKET":
            continue
        monkeypatch.setenv(k, v)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=str(tmp_path / "nope.env"))  # type: ignore[call-arg]
    # Check the missing field is named in the error.
    assert "r2_bucket" in str(exc_info.value).lower()


def test_rate_limit_must_be_positive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k, v in _REQUIRED_R2_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("INGEST_RATE_LIMIT_PER_SEC", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=str(tmp_path / "nope.env"))  # type: ignore[call-arg]


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _REQUIRED_R2_ENV.items():
        monkeypatch.setenv(k, v)
    # Bust any prior cache from earlier tests in this process.
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
