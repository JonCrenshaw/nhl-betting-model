"""Polite, rate-limited HTTP client with retries.

Design (per ``docs/milestones/m2-nhl-ingestion.md`` D6):

* Transport: ``httpx`` synchronous client. Single-threaded by design for
  M2 — parallelism arrives with Dagster at M10.
* Rate limiting: a per-instance token-bucket with a single token, so at
  most ``rate_per_sec`` requests are issued from one client regardless
  of caller threads.
* Retries: ``tenacity`` with exponential jitter on ``429`` / ``5xx``
  responses and on transport errors (DNS failure, connection reset,
  read timeout). ``max_retries=5`` by default; total wall budget per
  request capped by ``request_timeout_seconds`` per attempt.
* User-Agent: friendly and identifies us so the NHL can reach out if
  they object — ``"PuckBunny/0.1 (contact: …)"``.

The class is intentionally generic: no NHL knowledge here.
``puckbunny.ingestion.nhl`` (M2 PR-C) layers URL templates and response
parsing on top.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import structlog
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

# 429 (Too Many Requests) and the standard "transient backend" 5xx codes.
# 501 (Not Implemented) is intentionally excluded — retrying that just
# wastes the rate-limit budget.
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class RetryableStatusError(Exception):
    """Raised on a retryable HTTP status (429 / 5xx).

    ``tenacity`` retries on this exception. After the final attempt the
    instance escapes to the caller, who can inspect ``.response`` to log
    or branch on the failure.
    """

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(
            f"HTTP {response.status_code} on {response.request.method} {response.request.url}"
        )
        self.response: httpx.Response = response


def _is_retryable(exc: BaseException) -> bool:
    """tenacity predicate — retry on retryable status or transport errors."""
    if isinstance(exc, RetryableStatusError):
        return True
    return isinstance(exc, httpx.TransportError)


class RateLimitedClient:
    """A thin ``httpx`` wrapper that enforces a per-instance rate limit and retries.

    The rate limiter sleeps the calling thread to keep request spacing at
    or above ``1 / rate_per_sec``. Retries use exponential jitter, so two
    parallel processes sharing an upstream don't synchronize their retry
    waves.

    Example::

        with RateLimitedClient(
            rate_per_sec=2.0,
            user_agent="PuckBunny/0.1 (contact: ...)",
        ) as client:
            response = client.get("https://api-web.nhle.com/v1/schedule/2026-04-25")
            payload = response.json()
    """

    def __init__(
        self,
        *,
        rate_per_sec: float,
        user_agent: str,
        request_timeout_seconds: float = 60.0,
        max_retries: int = 5,
        retry_initial_wait_seconds: float = 1.0,
        retry_max_wait_seconds: float = 30.0,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")

        self._min_interval: float = 1.0 / rate_per_sec
        self._max_retries = max_retries
        self._retry_initial_wait_seconds = retry_initial_wait_seconds
        self._retry_max_wait_seconds = retry_max_wait_seconds
        self._lock = threading.Lock()
        self._last_request_at_monotonic: float = 0.0
        self._client = httpx.Client(
            base_url=base_url or "",
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(request_timeout_seconds),
            follow_redirects=True,
            transport=transport,
        )
        self._log = structlog.get_logger(__name__)

    # --- public API ---

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """GET ``url`` with rate-limit + retry, returning the final response.

        Raises:
            httpx.HTTPStatusError: Non-retryable ``4xx`` response.
            RetryableStatusError: All ``max_retries + 1`` attempts hit a
                retryable status code.
            httpx.TransportError: All attempts failed at transport
                level (DNS, connection, timeout).
        """
        return self._request("GET", url, params=params)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RateLimitedClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- internals ---

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        retryer = Retrying(
            retry=retry_if_exception(_is_retryable),
            wait=wait_exponential_jitter(
                initial=self._retry_initial_wait_seconds,
                max=self._retry_max_wait_seconds,
            ),
            stop=stop_after_attempt(self._max_retries + 1),
            reraise=True,
            before_sleep=self._log_retry_sleep,
        )

        def _attempt() -> httpx.Response:
            self._wait_for_slot()
            resp = self._client.request(method, url, params=params)
            if resp.status_code in _RETRYABLE_STATUS_CODES:
                raise RetryableStatusError(resp)
            resp.raise_for_status()
            return resp

        # ``Retrying`` is callable: it invokes ``fn`` under the retry
        # policy and returns its result, or re-raises after exhausting
        # attempts (because ``reraise=True``).
        return retryer(_attempt)

    def _wait_for_slot(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at_monotonic
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request_at_monotonic = time.monotonic()

    def _log_retry_sleep(self, retry_state: RetryCallState) -> None:
        outcome = retry_state.outcome
        exc = outcome.exception() if outcome is not None else None
        next_action = retry_state.next_action
        sleep_s = next_action.sleep if next_action is not None else None
        status: int | None = None
        if isinstance(exc, RetryableStatusError):
            status = exc.response.status_code
        self._log.warning(
            "http_retry",
            attempt=retry_state.attempt_number,
            sleep_seconds=sleep_s,
            error=str(exc) if exc else None,
            status=status,
        )
