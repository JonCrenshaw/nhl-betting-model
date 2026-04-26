"""Tests for ``puckbunny.http.client``.

We use ``httpx.MockTransport`` for these unit tests rather than
``pytest-recording`` cassettes because we're testing the *client's*
behavior (rate limit, retry, headers), not a specific upstream's
response shape. Cassettes shine in M2 PR-C/D where we record real NHL
API payloads. The dev dep is in place so that work can begin without
another dependency edit.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from puckbunny.http.client import RateLimitedClient, RetryableStatusError


def _client(
    handler,
    *,
    rate_per_sec: float = 100.0,
    max_retries: int = 3,
    user_agent: str = "PuckBunny-test/0.0",
    retry_initial_wait_seconds: float = 0.0,
    retry_max_wait_seconds: float = 0.0,
) -> RateLimitedClient:
    """Build a client wired to an in-memory ``MockTransport``."""
    transport = httpx.MockTransport(handler)
    return RateLimitedClient(
        rate_per_sec=rate_per_sec,
        user_agent=user_agent,
        max_retries=max_retries,
        retry_initial_wait_seconds=retry_initial_wait_seconds,
        retry_max_wait_seconds=retry_max_wait_seconds,
        transport=transport,
    )


def test_user_agent_header_is_set() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent", "")
        return httpx.Response(200, json={"ok": True})

    with _client(handler, user_agent="PuckBunny/0.1 (contact: test)") as client:
        resp = client.get("https://example.com/")

    assert resp.status_code == 200
    assert captured["ua"] == "PuckBunny/0.1 (contact: test)"


def test_rate_limiter_paces_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    rate = 10.0  # 10 req/sec → 100ms minimum spacing
    with _client(handler, rate_per_sec=rate) as client:
        start = time.monotonic()
        for _ in range(3):
            client.get("https://example.com/")
        elapsed = time.monotonic() - start

    # Three requests at 10/sec: first immediate, next two each wait ≥ 100 ms.
    # Allow generous tolerance for slow CI hosts.
    assert elapsed >= 2 * (1.0 / rate) * 0.9


def test_retries_then_succeeds_on_503() -> None:
    calls: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"err": "transient"})
        return httpx.Response(200, json={"ok": True})

    with _client(handler, max_retries=5) as client:
        resp = client.get("https://example.com/")

    assert resp.status_code == 200
    assert calls["n"] == 3


def test_retries_then_raises_after_exhaustion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with (
        _client(handler, max_retries=2) as client,
        pytest.raises(RetryableStatusError) as exc_info,
    ):
        client.get("https://example.com/")

    assert exc_info.value.response.status_code == 503


def test_retries_on_429() -> None:
    calls: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    with _client(handler, max_retries=3) as client:
        resp = client.get("https://example.com/")

    assert resp.status_code == 200
    assert calls["n"] == 2


def test_no_retry_on_404() -> None:
    calls: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    with _client(handler, max_retries=5) as client, pytest.raises(httpx.HTTPStatusError):
        client.get("https://example.com/")

    assert calls["n"] == 1


def test_get_passes_query_params() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={})

    with _client(handler) as client:
        client.get(
            "https://example.com/v1/schedule/2026-04-25",
            params={"key": "value", "n": 2},
        )

    assert seen["query"] == {"key": "value", "n": "2"}


def test_invalid_rate_per_sec_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    with pytest.raises(ValueError):
        RateLimitedClient(
            rate_per_sec=0.0,
            user_agent="x",
            transport=httpx.MockTransport(handler),
        )
