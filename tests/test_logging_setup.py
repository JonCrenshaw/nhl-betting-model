"""Tests for ``puckbunny.logging_setup``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from puckbunny import logging_setup

if TYPE_CHECKING:
    import pytest


def test_configure_logging_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    logging_setup.configure_logging(json_output=True, force=True)
    log = structlog.get_logger("puckbunny.test")
    log.info("hello", key="value", count=3)

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["key"] == "value"
    assert payload["count"] == 3
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_configure_logging_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    logging_setup.configure_logging(json_output=True, force=True)
    logging_setup.configure_logging(json_output=True)  # no force — should be no-op
    log = structlog.get_logger("puckbunny.test")
    log.info("hi")
    out = capsys.readouterr().out
    # Exactly one record emitted.
    assert out.strip().count("\n") == 0
