"""Shared pytest fixtures.

Test files import ``puckbunny`` directly; we don't add the src/ layout
manually — the editable install introduced in M2 PR-B handles it.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip ambient ``R2_*`` and ``INGEST_*`` vars so ``Settings()`` in
    tests doesn't accidentally pick up a developer's real ``.env``.

    Tests that need specific values can re-set them via ``monkeypatch``.
    """
    for key in list(os.environ):
        if key.startswith(("R2_", "INGEST_")):
            monkeypatch.delenv(key, raising=False)
    yield
