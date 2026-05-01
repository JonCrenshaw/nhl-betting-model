# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "httpx>=0.27",
# ]
# ///
"""PR-F0 spike — probe ``api.nhle.com/stats/rest/en``.

Sister script to ``tools/spike/pra_one_game.py`` (which de-risked the
``api-web.nhle.com`` game-level surface for PR-B/C/D). PR-F covers
season-scoped loaders (skater / goalie / team summaries plus rosters),
and the spike notes from PR-A flagged the stats-rest surface as an open
question:

    > ``api.nhle.com/stats/rest/v1/...`` wasn't exercised by this spike.
    > Adding it for PR-F (season summaries / rosters) is unchanged
    > risk — but worth one similar one-shot probe before PR-F starts.
                                                — pra-spike-notes §"Open questions"

(PR-A's reference to the surface as ``/stats/rest/v1/...`` carried
through into the M2 milestone doc and this script's first draft. The
spike's first run hit 404s and revealed the correct path is
``/stats/rest/en/...`` — captured in detail in
``docs/ideas/prf-stats-rest-spike-notes.md`` §"Surprises" #1.)

This script is the "one similar one-shot probe." Run it once, eyeball
the output, write findings into ``docs/ideas/prf-stats-rest-spike-notes.md``,
then PR-F1 (`season_summaries.py`) consumes those findings as its
contract. The branch ``spike/m2-stats-rest-probe`` is throwaway —
only the notes file gets cherry-picked into a non-spike PR.

What this answers
-----------------

1. **Pagination contract.** Does the surface use ``start``/``limit``
   query params? What's the default ``limit``? Does the response carry
   a ``total`` field we can loop on? What does the envelope look like
   (``data: [...]`` vs a bare array vs something else)?
2. **Page size cap.** What's the maximum ``limit`` honored? (Legacy
   stats portals capped at 100; we're verifying.)
3. **``limit=-1`` shortcut.** Some Sybase-derived APIs honor
   ``limit=-1`` as "all rows." Cheap to test, expensive if we assume
   it works and it silently truncates.
4. **Sort stability.** If we paginate, page N and page N+1 must come
   from a stable order or we'll mis-stitch results. Probe whether an
   explicit ``sort=`` param is honored and whether the default order
   is deterministic.
5. **Per-row size and projection.** Multiply observed row JSON size
   by ~1,000 skaters X 11 seasons to update the cost line — PR-A
   measured game-level bronze at ~350 MB; season-summaries should
   be a fraction of that, but worth confirming before PR-F1 ships.
6. **In-progress season behavior.** ``seasonId=20252026`` is mid-
   playoffs as of 2026-04-28. Does the surface return partial-season
   regular-season aggregates, or playoff aggregates, or something else?
   Affects whether daily-incremental even makes sense for these
   endpoints (probably not — once-weekly or post-season is plenty).

What this is NOT
----------------

* Not a load test. Three completed-season requests + a few pagination
  walks per endpoint. We're polite.
* Not writing to R2 or building any of the bronze-typed-envelope shape
  PR-F1 will use — it's just printing JSON shape and counts. The
  bronze writer is solved (PR-B/C primitives); the open question is
  the API contract.
* Not exercising ``/v1/roster/{TEAM}/{SEASON}`` or
  ``/v1/club-schedule-season/{TEAM}/{SEASON}``. Those live on
  ``api-web.nhle.com`` — same surface PR-A already validated. PR-F2
  picks them up directly without a probe.

How to run
----------

Single-file PEP 723 script — uv resolves deps inline, no project
install needed::

    uv run --no-project tools/spike/prf_stats_rest_probe.py

Pipe stdout to a file if you want to paste it into the notes::

    uv run --no-project tools/spike/prf_stats_rest_probe.py > /tmp/prf_probe.txt

Exit code is 0 on success, non-zero only if a request returns an
unexpected HTTP status — the script is intentionally tolerant about
*shape* surprises (we want to learn them) and intolerant about
*availability* failures (those should block the probe).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Base for the stats REST surface. Distinct from the ``api-web`` host
#: PR-A probed; both surfaces are unauthenticated and accept the same
#: identifying ``User-Agent``.
#:
#: NOTE: The M2 plan originally wrote this as ``/stats/rest/v1`` —
#: that's wrong. ``/v1/`` is the path convention on ``api-web.nhle.com``,
#: not on this surface. The stats-rest surface uses
#: ``/stats/rest/{lang}/{entity}/{report}`` with a mandatory language
#: segment. ``en`` is the only locale we care about. PR-H's ADR-0003
#: needs to capture this correction; M2 milestone doc D1 + scope list
#: should be updated at the same time.
STATS_BASE: str = "https://api.nhle.com/stats/rest/en"

#: Most recent fully-concluded NHL season as of 2026-04-28. Stable
#: row counts make this the right baseline for size and ``total``
#: assertions; ``20252026`` is mid-playoffs and used as the "what
#: does in-progress look like" comparison case.
COMPLETED_SEASON: str = "20242025"
IN_PROGRESS_SEASON: str = "20252026"

#: Endpoints in scope for PR-F1. Order matters for the print log only —
#: skater is first because it's the one we *expect* to paginate (~1k
#: skaters in a season), making it the most informative pagination
#: probe.
ENDPOINTS: tuple[str, ...] = (
    "skater/summary",
    "goalie/summary",
    "team/summary",
)

#: Polite identification — same shape as PR-A and the future PR-B
#: rate-limited client. If NHL ever needs to reach us, this is the
#: contact path.
USER_AGENT: str = "PuckBunny/0.1-spike (contact: crenshaw.jonathan@gmail.com)"

#: Per-request wall budget. Stats REST has historically been slower
#: than ``api-web``; 30s is generous.
REQUEST_TIMEOUT_S: float = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    """One ``GET`` against the stats-rest surface.

    Captured fields are the ones PR-F1 needs to write its loader
    against; everything else is interesting-but-not-load-bearing and
    gets dumped via ``raw_first_row`` for eyeballing.

    ``error_body`` is populated for non-2xx responses only — the
    stats-rest surface returns a structured ``{message, status, url}``
    error envelope, and capturing the message is essential for
    diagnosing path/parameter mistakes (the first probe run hit 404s
    because the M2 plan documented a non-existent ``/v1/`` segment;
    body content was the disambiguator).
    """

    url: str
    status: int
    envelope_keys: list[str]
    data_len: int
    total: int | None
    page_info: dict[str, Any] | None
    raw_first_row: dict[str, Any] | None
    body_bytes: int
    error_body: dict[str, Any] | None = None


def _get(client: httpx.Client, path: str, params: dict[str, Any]) -> ProbeResult:
    """One GET; returns a ``ProbeResult`` summarising the response.

    Doesn't raise on non-200 — we want to *see* a 4xx/5xx if it
    happens, not abort the probe. The caller decides whether the
    overall script should exit non-zero.
    """
    url = f"{STATS_BASE}/{path}"
    response = client.get(url, params=params)
    body = response.content
    parsed: dict[str, Any] | list[Any]
    try:
        parsed = response.json()
    except ValueError:
        parsed = {}

    # The legacy stats portal returns ``{"data": [...], "total": N,
    # ... }``. We don't assume that — extract whatever keys the
    # surface actually returns and let the caller eyeball them.
    envelope_keys: list[str]
    data: list[Any]
    total: int | None
    page_info: dict[str, Any] | None

    if isinstance(parsed, dict):
        envelope_keys = sorted(parsed.keys())
        raw_data = parsed.get("data")
        data = raw_data if isinstance(raw_data, list) else []
        total_value = parsed.get("total")
        total = int(total_value) if isinstance(total_value, int) else None
        # Some Sybase-flavored surfaces return a ``pageInfo`` block.
        # If present, capture it verbatim for the notes file.
        page_info_value = parsed.get("pageInfo")
        page_info = page_info_value if isinstance(page_info_value, dict) else None
    elif isinstance(parsed, list):
        # Bare-array response would be a notable surprise — record it
        # so the notes file can flag the divergence.
        envelope_keys = ["<bare array>"]
        data = parsed
        total = None
        page_info = None
    else:
        envelope_keys = ["<unparseable>"]
        data = []
        total = None
        page_info = None

    raw_first_row = data[0] if data and isinstance(data[0], dict) else None

    # On non-2xx, capture the structured error body verbatim so the
    # printed output explains *why* — without this we only saw status
    # codes on the first run and couldn't tell ``/v1/`` was wrong vs
    # rate-limited vs auth.
    error_body: dict[str, Any] | None = None
    if not (200 <= response.status_code < 300) and isinstance(parsed, dict):
        error_body = parsed

    return ProbeResult(
        url=str(response.url),
        status=response.status_code,
        envelope_keys=envelope_keys,
        data_len=len(data),
        total=total,
        page_info=page_info,
        raw_first_row=raw_first_row,
        body_bytes=len(body),
        error_body=error_body,
    )


def _print_result(label: str, result: ProbeResult) -> None:
    """Pretty-print one probe result. Format is human-skim-friendly,
    not machine-parseable — the spike notes are the structured artifact.
    """
    print(f"\n=== {label} ===")
    print(f"  url:            {result.url}")
    print(f"  status:         {result.status}")
    print(f"  envelope_keys:  {result.envelope_keys}")
    print(f"  data_len:       {result.data_len}")
    print(f"  total:          {result.total}")
    print(f"  pageInfo:       {result.page_info}")
    print(f"  body_bytes:     {result.body_bytes}")
    if result.raw_first_row is not None:
        first_row_json = json.dumps(result.raw_first_row, indent=2, sort_keys=True)
        # Keep the printed sample short — first row is enough to see
        # the shape, full pages would drown the spike output.
        if len(first_row_json) > 1500:
            first_row_json = first_row_json[:1500] + "\n  ... [truncated]"
        print(f"  first_row:\n{first_row_json}")
    else:
        print("  first_row:      <none>")
    if result.error_body is not None:
        # Print the full error envelope — it's tiny (typical 155 bytes
        # observed) and the ``message`` field tells us exactly what
        # went wrong.
        print(f"  error_body:     {json.dumps(result.error_body, sort_keys=True)}")


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def probe_default(client: httpx.Client, endpoint: str) -> ProbeResult:
    """Hit endpoint with only the season filter — no ``start``/``limit``.

    Tells us the *default* page size, which is what a naive loader
    would see on day 1. If default is 25 (the legacy default) we'll
    need to paginate aggressively; if it's larger, less so.
    """
    return _get(
        client,
        endpoint,
        params={"cayenneExp": f"seasonId={COMPLETED_SEASON}"},
    )


def probe_explicit_limit(client: httpx.Client, endpoint: str, limit: int) -> ProbeResult:
    """Hit endpoint with an explicit ``limit``.

    Probes the cap. Calling sites pass ``100`` (legacy expected cap)
    and ``200`` (well above) — if both return the same row count, the
    cap is between 100 and 200 and we know to chunk at 100.
    """
    return _get(
        client,
        endpoint,
        params={
            "cayenneExp": f"seasonId={COMPLETED_SEASON}",
            "start": 0,
            "limit": limit,
        },
    )


def probe_limit_minus_one(client: httpx.Client, endpoint: str) -> ProbeResult:
    """Hit endpoint with ``limit=-1``.

    Some Sybase-derived APIs honor this as "return everything." If it
    works, the loader skips pagination entirely; if it silently caps
    at the default, we must NOT rely on it. The data_len vs total
    comparison in the printed output is the answer.
    """
    return _get(
        client,
        endpoint,
        params={
            "cayenneExp": f"seasonId={COMPLETED_SEASON}",
            "start": 0,
            "limit": -1,
        },
    )


def probe_paginated_walk(
    client: httpx.Client,
    endpoint: str,
    *,
    page_size: int = 100,
    max_pages: int = 3,
) -> list[ProbeResult]:
    """Walk the first ``max_pages`` pages of ``endpoint`` at ``page_size``.

    Three pages is enough to see whether ``start`` advances correctly
    and whether row identity changes between pages — the eyeball check
    is "first row of page 1 ≠ first row of page 2 and page-2 first
    row matches page-1 last row + 1 in whatever sort key is in play."
    Caller does the eyeballing in the printed output.
    """
    results: list[ProbeResult] = []
    for page in range(max_pages):
        result = _get(
            client,
            endpoint,
            params={
                "cayenneExp": f"seasonId={COMPLETED_SEASON}",
                "start": page * page_size,
                "limit": page_size,
                # Stable sort — playerId is monotonic and present on
                # every player row. If the surface ignores ``sort``,
                # we'll see the same row appear on multiple pages or
                # gaps; if it honors it, pages will tile cleanly.
                "sort": '[{"property":"playerId","direction":"ASC"}]',
            },
        )
        results.append(result)
        # Short-circuit if the page came back empty — no point hammering
        # past the end of the dataset just to confirm it's empty.
        if result.data_len == 0:
            break
    return results


def probe_in_progress_season(client: httpx.Client, endpoint: str) -> ProbeResult:
    """Hit endpoint for the current season (mid-playoffs at probe time).

    Tells us whether the surface returns partial-season regular-season
    aggregates (most likely), playoff aggregates (unlikely without an
    extra filter), or rejects an in-progress ``seasonId``. Drives the
    "is daily incremental even relevant for these endpoints" call in
    the spike notes — if numbers refresh slowly relative to the daily
    cadence, season-summaries belong on a weekly schedule, not the
    daily walker PR-E built.
    """
    return _get(
        client,
        endpoint,
        params={
            "cayenneExp": f"seasonId={IN_PROGRESS_SEASON}",
            "start": 0,
            "limit": 100,
        },
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the probe set against all three endpoints; print findings.

    Returns 0 on success. Returns non-zero if any probe came back with
    a non-2xx status — that's a structural blocker we must understand
    before PR-F1, not a "shape surprise" we just learn from.
    """
    print("PR-F0 — api.nhle.com/stats/rest/v1 probe")
    print(f"  completed season:    {COMPLETED_SEASON}")
    print(f"  in-progress season:  {IN_PROGRESS_SEASON}")
    print(f"  endpoints:           {', '.join(ENDPOINTS)}")

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    bad_status: list[str] = []

    with httpx.Client(timeout=REQUEST_TIMEOUT_S, headers=headers) as client:
        for endpoint in ENDPOINTS:
            print(f"\n############ {endpoint} ############")

            default_result = probe_default(client, endpoint)
            _print_result(f"{endpoint} :: default (no start/limit)", default_result)
            if not (200 <= default_result.status < 300):
                bad_status.append(f"{endpoint} default -> {default_result.status}")

            for limit in (100, 200):
                result = probe_explicit_limit(client, endpoint, limit)
                _print_result(f"{endpoint} :: limit={limit}", result)
                if not (200 <= result.status < 300):
                    bad_status.append(f"{endpoint} limit={limit} -> {result.status}")

            limit_neg = probe_limit_minus_one(client, endpoint)
            _print_result(f"{endpoint} :: limit=-1", limit_neg)
            if not (200 <= limit_neg.status < 300):
                bad_status.append(f"{endpoint} limit=-1 -> {limit_neg.status}")

            # Pagination walk only makes sense when the dataset is big
            # enough to span multiple pages. Skip for endpoints whose
            # default page already returned everything.
            walk_worth_it = (
                default_result.total is not None and default_result.total > 100
            ) or default_result.data_len >= 100
            if walk_worth_it:
                walk = probe_paginated_walk(client, endpoint, page_size=100, max_pages=3)
                for idx, page_result in enumerate(walk):
                    _print_result(
                        f"{endpoint} :: page {idx + 1} (start={idx * 100}, limit=100)",
                        page_result,
                    )
                    if not (200 <= page_result.status < 300):
                        bad_status.append(f"{endpoint} page={idx + 1} -> {page_result.status}")
            else:
                print(f"\n  (skipping pagination walk for {endpoint} — dataset fits in one page)")

            in_prog = probe_in_progress_season(client, endpoint)
            _print_result(f"{endpoint} :: season={IN_PROGRESS_SEASON} (in-progress)", in_prog)
            if not (200 <= in_prog.status < 300):
                bad_status.append(f"{endpoint} in-progress -> {in_prog.status}")

    print("\n=== summary ===")
    if bad_status:
        print("  non-2xx responses:")
        for line in bad_status:
            print(f"    - {line}")
        print("  -> probe FAILED; investigate before PR-F1.")
        return 1
    print("  all probes returned 2xx.")
    print("  -> next step: write docs/ideas/prf-stats-rest-spike-notes.md from this output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
