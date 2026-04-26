"""HTTP transport primitives shared across PuckBunny ingestion code.

The single public surface is :class:`puckbunny.http.client.RateLimitedClient`,
a polite, retrying ``httpx``-backed client. NHL-specific URL builders and
response models live in ``puckbunny.ingestion.nhl`` (added in M2 PR-C).
"""

from __future__ import annotations

from puckbunny.http.client import RateLimitedClient, RetryableStatusError

__all__ = ["RateLimitedClient", "RetryableStatusError"]
