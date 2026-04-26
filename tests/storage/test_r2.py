"""Tests for ``puckbunny.storage.r2``.

The unit-test surface is small: we verify ``R2Credentials.from_settings``
and the boto3 client construction succeeds with realistic kwargs. Tests
that round-trip against a real R2 bucket live behind
``@pytest.mark.integration`` and are excluded from default CI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from puckbunny.config import Settings
from puckbunny.storage.r2 import R2Credentials, R2ObjectStorage

if TYPE_CHECKING:
    import pytest


def _settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Settings:
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "puckbunny-lake")
    return Settings(_env_file=str(tmp_path / "nope.env"))  # type: ignore[call-arg]


def test_credentials_from_settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = _settings(monkeypatch, tmp_path)
    creds = R2Credentials.from_settings(settings)
    assert creds.bucket == "puckbunny-lake"
    assert creds.region == "auto"
    assert creds.endpoint_url == "https://acct.r2.cloudflarestorage.com"


def test_r2_storage_constructible(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Smoke test: client construction does not raise."""
    settings = _settings(monkeypatch, tmp_path)
    storage = R2ObjectStorage.from_settings(settings)
    # Internal client should be a boto3 S3 client; we don't exercise it
    # without integration credentials.
    assert hasattr(storage, "put_object")
    assert hasattr(storage, "list_objects")
