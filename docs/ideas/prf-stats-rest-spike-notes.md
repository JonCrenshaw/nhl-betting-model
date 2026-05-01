# PR-F0 spike notes — `api.nhle.com/stats/rest/en` probe

**Branch.** `spike/m2-stats-rest-probe` (throwaway, not for merge to main; cherry-pick this notes file when consuming).
**Date.** 2026-04-28.
**Goal.** Validate the stats-rest surface contract before writing PR-F1 (`season_summaries.py`). PR-A left this surface as an open question; this note closes it. See `docs/milestones/m2-nhl-ingestion.md` PR-F section and `docs/ideas/pra-spike-notes.md` open questions.

---

## What ran

`tools/spike/prf_stats_rest_probe.py` (PEP 723 inline-deps script, `uv run --no-project`) hit each of the three season-scoped endpoints — `skater/summary`, `goalie/summary`, `team/summary` — against:

- `seasonId=20242025` — most recent fully-concluded season; stable counts, the right baseline for pagination and size assertions.
- `seasonId=20252026` — mid-playoffs at probe time; the "in-progress comparison" case.

For each (endpoint, season) the probe ran six variants: default (no `start`/`limit`), `limit=100`, `limit=200`, `limit=-1`, a 3-page walk at `limit=100` with `sort=playerId ASC`, and the in-progress season at `limit=100`.

---

## Confirmations of the M2 plan

| Plan item | Status |
|-----------|--------|
| **D1.** `api.nhle.com/stats/rest/...` is reachable, returns 200s for all three season-summary endpoints, accepts our identifying `User-Agent`, no auth required. | Confirmed — **but the path is `/stats/rest/en/...`, not `/stats/rest/v1/...`** (see Surprise §1). |
| **D3.** Typed-envelope-plus-raw-JSON row shape generalizes from the game-level endpoints to the season-scoped ones. The natural-key field is `playerId` (skater/goalie) or `teamId` (team), and `seasonId` (int) populates the existing `season` column — no schema change. | Confirmed. |
| **D6.** Polite UA + plain `httpx` GET works without rate-limiter or retries. | Confirmed across ~30 requests. PR-B's rate-limited client will still front this surface in PR-F1; spike just shows the surface tolerates a polite default. |
| **Endpoint key fields exist.** `seasonId`, `playerId`/`teamId`, `gamesPlayed`, `goals`, `assists`, `points`, `teamAbbrevs` all populate cleanly on the first row of every response. | Confirmed. |

### Storage / cost data points

Per-season uncompressed JSON sizes:

| Endpoint | Rows / season (2024-25) | JSON bytes | Bytes/row |
|----------|-----------------------:|-----------:|----------:|
| skater/summary | 963 | 441,015 | ~458 |
| goalie/summary | 105 | 41,724 | ~397 |
| team/summary | 32 | 16,862 | ~528 |
| **Per-season total** | — | **~500 KB** | — |

Extrapolating to the M2 backfill scope (11 seasons, 2015-16 → 2025-26):

- **JSON-uncompressed total ≈ 5.5 MB** across all three endpoints, all seasons.
- Applying the ~8× zstd ratio measured on PR-A's PxP, compressed bronze comes in **under 1 MB total** for the entire season-summaries layer.
- Compared with PR-A's measured ~350 MB game-level bronze, season summaries are **~0.3% of game-level** — three orders of magnitude smaller than the part we already verified is well inside the cost ceiling. No reason to revisit D2 or the cost section.

---

## Surprises and things worth knowing before PR-F1

### 1. **The M2 plan's URL shape is wrong: `/stats/rest/v1` does not exist.**

The first probe run (with the URL the M2 doc documented) returned 404s on every request. The actual base path is `https://api.nhle.com/stats/rest/en/...` — a mandatory locale segment, no `/v1/`. The 404 body — `{"message":"Endpoint not found","status":404,"url":"..."}` — was the disambiguator.

`/v1/` is the path convention on `api-web.nhle.com` (the surface PR-A probed and PR-C/D/E built against). It does **not** apply to `api.nhle.com/stats/rest/...`. Two surfaces, two different versioning conventions.

**Action.** Fix `docs/milestones/m2-nhl-ingestion.md` D1 and the "Endpoints in scope for M2" list before PR-F1 lands. Also bake the corrected URL into ADR-0003 (PR-H). The probe script has the corrected base in `STATS_BASE` with a code comment flagging the diff.

### 2. **Pagination: `limit=-1` returns the whole result set in one shot.**

Cleanest possible contract. The probe confirmed:

- Response envelope: `{"data": [...], "total": N}`. No `pageInfo` block. `total` is the only loop signal.
- Default `limit` (when omitted): **50** rows. Not the legacy 25, not "everything."
- Hard cap at `limit=100`. `limit=200` returned exactly 100 rows silently — **no error, no warning, just a cap**. Anyone naively passing `limit=200` would get a truncated dataset they don't notice. Worth a defensive check in the loader (see Action below).
- `limit=-1` returned **all** rows in one response: 963 skaters, 105 goalies, 32 teams. `len(data) == total` held for every endpoint.

**Action for PR-F1.** Use `limit=-1` and skip pagination entirely. The loader is one GET per `(endpoint, season)`, full stop. Defensive assertion: after the fetch, `assert len(parsed["data"]) == parsed["total"]` before writing bronze and committing the manifest entry. If that ever fails — surface change, partial response, anything — fail loud, don't silently store a truncated dataset.

### 3. **`limit=-1` makes `scope_key = season` correct.**

Pre-spike I'd hedged this on whether pagination would force `scope_key = f"{season}|page={n}"`. With `limit=-1` there is no pagination, so the hedging is moot.

**Action for PR-F1.** Manifest entries use `scope_key = season` (e.g. `"20242025"`) for all three endpoints. One row in `bronze/_manifests/ingest_runs.jsonl` per `(endpoint, season)` successful fetch, matching D7's intent that one entry = one logical unit of work.

### 4. **Default sort is NOT `playerId` — explicit sort is required for stable pagination.**

Even though `limit=-1` makes our M2 loader paginate-free, this matters for any future use that pages: the default order isn't deterministic by any field we'd predict. The probe's default request returned Sean Kuraly (`playerId=8476374`) as row 0. The explicit `sort=playerId ASC` request returned Ryan Suter (`playerId=8470600`) as row 0 — the actual lowest-`playerId` row in the season.

The 3-page walk with `sort=playerId ASC` tiled cleanly: page 1 starts at Suter (8470600), page 2 at Merrill (8475750), page 3 at Faksa (8476889) — monotonically increasing.

**Action for PR-F1.** Loader uses `limit=-1` (no pagination), so `sort=` isn't needed in the request. Bronze still stores the response verbatim, so silver gets whatever order the server returned. **Document this as a known property** so a future "let's paginate this for some reason" change doesn't silently break.

### 5. **Game-type aggregation is implicit — and suspicious.**

The unfiltered response combines game types in a way that's not obvious:

| Player / Team | Season | `gamesPlayed` | Interpretation |
|----|----|----:|----|
| Washington Capitals | 2024-25 (final) | 92 | 82 regular + ~10 playoff (deep run) |
| Sean Kuraly (CBJ) | 2024-25 (final) | 82 | Regular only — CBJ missed playoffs |
| Washington Capitals | 2025-26 (in-progress, mid-playoffs) | 82 | Regular only — playoff games not yet aggregated |

Two things matter:

- **For finalized seasons, the unfiltered response includes playoffs.** Silver-layer "regular-season points" derived from this fetch is wrong by however many points a player added in the playoffs.
- **For in-progress seasons, playoff games may not appear immediately** — there's some backend aggregation cadence we don't know yet. (May be nightly, may be after series conclude, may be after the SCF — TBD.)

**Action for PR-F1 — open decision.** Three options, in order of effort:

1. **Cheapest:** Don't filter by `gameTypeId`. Store the combined-aggregate as bronze; silver knows it's combined and doesn't try to decompose. Acceptable if season summaries are only used as season-level priors / static features in modeling. **Recommended for PR-F1** — the simpler thing to ship; revisit if M4 modeling needs game-type-broken-out aggregates.
2. **Medium:** Fetch each season twice — once with `cayenneExp=seasonId={S} and gameTypeId=2` (regular), once with `gameTypeId=3` (playoff). Store as separate bronze rows; `scope_key = f"{season}|gtype={gtype}"`. Doubles the request count (~22 vs 11 across the backfill — still trivial) and lets silver compute either view cleanly.
3. **Most flexible:** Fetch all three combinations (combined, regular-only, playoff-only). Even more redundancy; not warranted at our scale.

The cheapest path is the right PR-F1 default. Capture the decision in ADR-0003 with a revisit trigger ("if M4 surfaces a need for regular-season-only player priors, switch to medium").

### 6. **In-progress-season cadence: weekly is plenty, daily is wasteful.**

`seasonId=20252026` returned 973 skaters, 100 goalies, 32 teams — populated, but the Capitals' GP=82 suggests playoff games aren't yet folded in. Even if the backend updates these aggregates daily during regular season, mid-playoff updates appear lagged. Daily ingest of season summaries during the 9-month season is mostly a no-op (numbers move slowly week-to-week) and during playoffs may be stale anyway.

**Action for PR-F1.** Don't wire `season_summaries` into the daily walker that PR-E built. Instead:

- **Backfill mode (PR-G):** one fetch per `(endpoint, season)` for every completed season.
- **Maintenance mode:** one fetch per current season per week (cron / Dagster schedule in M10), plus a one-shot post-Stanley-Cup-Final pull to capture finalized totals. Surface this cadence call out in the PR-F1 README / module docstring; the schedule itself is M10's problem.

Treating this loader as "weekly + post-SCF" not "daily" is the right cadence and reduces noise in the manifest.

### 7. **Multi-team players: `teamAbbrevs` is a comma-joined string.**

Traded players surface a single-string field like `"teamAbbrevs": "ANA,BUF"`. Single column, easy to handle. James Reimer split between Anaheim and Buffalo in 2024-25 is the row I happened to land on as the goalie example.

**Action.** No bronze schema change. Silver's M3 work splits this string at parse time when constructing the player-team bridge. Worth a glossary entry (`docs/glossary.md` already exists) noting the convention.

### 8. **Some columns are nullable in idiomatic ways.**

`faceoffWinPct: null` for non-faceoff-takers (defensemen, wingers). `ties: null` everywhere — vestigial from pre-shootout-era schemas. Numeric fields like `assists`, `goals`, `gamesPlayed` are non-null integers. `pyarrow`'s schema inference handles this correctly so long as we feed it the response rows directly without first JSON-stringifying numeric values.

**No action needed**, just don't pre-coerce nulls to zero anywhere in the pipeline.

---

## Open questions / parked

- **In-progress season aggregation cadence is unknown.** We saw `seasonId=20252026` returning regular-season-final-style numbers despite playoffs being underway. Whether playoff games get merged in nightly, weekly, or only after the SCF is something we'd only learn by watching values drift over time. Not blocking PR-F1; the recommended cadence (weekly + post-SCF) absorbs whatever the answer is.
- **`gameTypeId` decision is deferrable.** The recommended PR-F1 default is "fetch unfiltered, accept combined." If M4 reveals a need to separate regular-season vs playoff aggregates, the medium option (two fetches per season) is straightforward — same code path, doubled scope_key. ADR-0003 should capture the decision and revisit trigger.
- **Roster + club-schedule-season endpoints (PR-F2) are unprobed but lower-risk** — they live on `api-web.nhle.com`, the same surface PR-A validated, with the same `/v1/` versioning and unauth/`User-Agent` posture. Per-team payloads should be small (<25 KB each); 32 teams × 11 seasons = 352 fetches, still trivial. PR-F2 doesn't need its own spike; it needs its own implementation.
- **Did not stress-test rate behavior on this surface.** Probe was ~30 requests, polite. PR-B's tenacity retries should still cover us; if `api.nhle.com` rate-limits differently than `api-web.nhle.com`, we'll find out during PR-F1 testing.

---

## Recommendation

**Proceed to PR-F1 (`season_summaries.py`) as planned, with the following inputs hardened by this spike:**

1. **URL base:** `https://api.nhle.com/stats/rest/en` (not `/v1`). Fix the M2 doc and ADR-0003 wording at the same time.
2. **Request shape:** `GET {base}/{endpoint}?cayenneExp=seasonId={SEASON}&limit=-1`. No pagination. No `gameTypeId` filter (recommended default; capture decision in ADR-0003 with revisit trigger).
3. **Defensive assertion:** `assert response["total"] == len(response["data"])` before writing bronze.
4. **Manifest:** `scope_key = season` (e.g. `"20242025"`). One entry per `(endpoint, season)`.
5. **Bronze envelope:** unchanged from PR-C/D — natural key column sources from `playerId` (skater/goalie) or `teamId` (team); `seasonId` populates the typed-envelope `season` column (coerce int → str on write to match the existing convention).
6. **Cadence:** PR-F1 ships the loader; do not auto-wire it into PR-E's daily walker. M10 schedules it weekly + post-SCF.
7. **Pydantic schemas:** per-endpoint, mirroring PR-C's pattern. `SkaterSummaryResponse` / `GoalieSummaryResponse` / `TeamSummaryResponse` each model the `{data, total}` envelope plus a typed row schema. The row schemas overlap on common fields (`seasonId`, `playerId`/`teamId`, `gamesPlayed`, `goals`, `assists`, `points`) but diverge enough on the rest (faceoff %, save %, team-only fields like `pointPct` and `regulationAndOtWins`) to not bother sharing a base model.

PR-F2 (`roster.py` + `/v1/club-schedule-season/...`) does not need a spike; it's well within the surface PR-A already validated. Implement directly.

D1–D7 stand. The cost projection moves further inside the ceiling. Bronze layout is unchanged.
