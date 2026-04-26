"""Ingestion package — bronze loaders for external data sources.

Sport-specific loaders live in subpackages (``puckbunny.ingestion.nhl``
in M2; ``puckbunny.ingestion.mlb`` etc. in Phase 3). The split keeps
sport-agnostic primitives (``puckbunny.http``, ``puckbunny.storage``,
``puckbunny.config``) cleanly separated from per-sport URL templates and
response shapes.
"""

from __future__ import annotations
