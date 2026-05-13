# ADR-0003: NHL API surface and bronze shape

**Status.** Accepted
**Date.** 2026-05-11
**Deciders.** Jon

## Context

M2 lands the NHL ingestion layer: historical and daily game, skater, goalie,
and play-by-play data into bronze as partitioned Parquet in Cloudflare R2,
plus the season-scoped loaders and the backfill orchestrator that drives
them. ADR-0001 already settled the warehouse stack (R2 + DuckDB/MotherDuck +
dbt); this ADR captures the ingestion-layer decisions that sat downstream of
that choice and have now shipped across PR-A through PR-G.

The long-form reasoning (options considered, tradeoffs walked) lives in
[`docs/milestones/m2-nhl-ingestion.md`](../milestones/m2-nhl-ingestion.md)
under "Open decisions and proposed answers" (D1–D11), and in
[`docs/ideas/prf-stats-rest-spike-notes.md`](../ideas/prf-stats-rest-spike-notes.md)
for the D12 `gameTypeId` decision surfaced by the PR-F0 spike. This ADR
is the durable index — what we chose, and what would force us to reopen
it.

## Decisions

### D1. NHL API surface

**Decision.** Modern `api-web.nhle.com` + `api.nhle.com/stats/rest/en` as
the primary surface, no fallback layer. The legacy `statsapi.web.nhl.com`
was effectively deprecated in 2023; committing to the modern surface avoids
a shim layer for a deprecated API.

**Revisit if.** A needed endpoint turns out to only be on the legacy
surface — add a narrow one-off pull and append this ADR rather than
building general fallback logic.

### D2. Bronze partitioning

**Decision.** `bronze/nhl_api/{endpoint}/ingest_date=YYYY-MM-DD/*.parquet`.
Endpoint partition names mirror the URL slug exactly (hyphenated:
`play-by-play`, `skater-summary`, `club-schedule-season`, etc.) so a bronze
path is greppable against the source URL. Season is a column inside the
payload, not a partition key.

**Revisit if.** Point-in-time reproduction stops being the dominant access
pattern (e.g., we move to CDC-style ingest), or if cross-endpoint
partition-pruning queries become a bottleneck at silver-build time.

### D3. Bronze payload shape

**Decision.** Typed envelope plus raw JSON per row. Columns: `game_id` or
`entity_id` (natural key), `season`, `game_date` or `as_of_date`,
`endpoint` (URL template), `endpoint_params_json`, `fetched_at_utc`,
`response_json` (verbatim API body), `response_sha256` (dedupe key).
PR-A's spike confirmed all three game-level endpoints carry an integer
`id` field that sources the natural key.

Per-endpoint pydantic models (not a single shared "game" schema): the
three game-level endpoints overlap heavily but each has unique top-level
fields (`landing` has `venueTimezone`, `boxscore` has `playerByGameStats`,
`play-by-play` has `plays` and `rosterSpots`). Schemas use
`extra="allow"` to tolerate schema drift; three PxP event types
(`period-start`, `period-end`, `game-end`) carry no `details` block and
are known exceptions silver M3 handles explicitly.

**Revisit if.** NHL ships an OpenAPI spec stable enough to make
`response_json` redundant, or a future endpoint family lacks a clean
natural key.

### D4. Historical backfill strategy

**Decision.** One parameterized loader path invoked across seasons —
backfill is `for season in range: loader.run(season=season)`, same code
path as daily ingest. Scope: 2015–16 through current. No separate
one-shot script; the daily job is the only one that stays alive long
enough to rot, and keeping paths unified surfaces rot in backfill too.

**Revisit if.** Backfill scope expands materially (pre-2015-16 history,
multi-sport bronze) or daily/backfill behavior divergence becomes a
maintenance burden.

### D5. Package name and location

**Decision.** Package name `puckbunny`. Location `src/puckbunny/ingestion/nhl/`.
Sport-agnostic naming so Phase 3 sports don't live under an NHL-branded
namespace.

**Revisit if.** Phase 3 multi-sport branding forces a parent-brand
rename (per the hockey-specific-name caveat in `CLAUDE.md`).

### D6. Rate-limiting and retry posture

**Decision.** `httpx` (sync) + `tenacity`. 2 req/sec default
(config-overridable), exponential backoff with jitter on 429/5xx, max 5
retries, per-request wall budget ≤60s. `User-Agent:
PuckBunny/0.1 (contact: crenshaw.jonathan@gmail.com)`. Single-threaded
for M2; parallelism comes with Dagster at M10.

**Revisit if.** NHL starts 403'ing or 429'ing under the polite default,
or M10's parallelism design needs a different posture (e.g., a token
bucket shared across Dagster workers).

### D7. Idempotency and resume semantics

**Decision.** Append-only JSONL manifest at
`bronze/_manifests/ingest_runs.jsonl`. One row per
`(endpoint_template, scope_key)` successful fetch:
`{run_id, endpoint, scope_key, fetched_at_utc, rows, bytes, status}`.
Both daily and backfill consult it to compute what's missing. M2 ships a
single-process reader-writer (read full file, append in memory, write
back) — fine at our volume.

**Revisit if.** Concurrent writers appear (M10 Dagster wiring is the
likely trigger), or the manifest grows past the point where rewriting
the full file per append is acceptable.

### D8. Game discovery for backfill

**Decision.** Pure schedule day-walks via `DailyLoader.load_date(date)`
for every calendar day in the season window (Sept 1 of start year through
June 30 of end year). Empty days are no-ops; preseason games are ingested
into bronze if the schedule returns them (bronze is source-shaped; silver
M3 decides relevance). Two alternatives were considered (date set from
`club-schedule-season` after team-season phase; step-by-7 day-walks) and
rejected — day-walks pay an irrelevant wall-time cost (~30 min for
~3,600 schedule fetches against ~5–6 hours of game-endpoint fetches that
dominate) for the benefit of identical daily/backfill code paths.

Ingestible game-state set: `{FINAL, OFF}` (constant `INGESTIBLE_GAME_STATES`
in `endpoints.py`). Spike confirmed playoff games return `OFF` rather
than `FINAL`.

**Revisit if.** Schedule-fetch wall time becomes a meaningful portion of
backfill time (today it's ~10% of game-endpoint time), or NHL changes
how game-state values map to "done."

### D9. Backfill subcommand layout

**Decision.** Single `backfill` subcommand with a `--loader
{games,season-summaries,team-season,all}` selector defaulting to `all`.
`--from-season` / `--to-season` accept both `YYYY-YY` and `YYYYYYYY` —
normalized via `format_season_id` + `parse_season_range`. The same
two-shape acceptance was extended to `--season` on `team-season` and
`season-summaries` in PR-G so the CLI surface stays consistent across
subcommands.

`all` runs phases in this order so cheap, low-volume phases fail fast
before burning hours on game-level fetches: **team-season → season-summaries → games**.

**Revisit if.** New loader phases appear (M4 odds is the likely trigger)
and the `--loader` taxonomy starts feeling forced, or a use case emerges
that needs more granular control than `--loader` + `--from-season` /
`--to-season` provides.

### D10. Cost-check methodology

**Decision.** End-of-loader-phase + end-of-overall projection against
`bytes_cumulative` (sum across manifest entries). Project monthly storage
cost as `bytes_cumulative / 1024³ × $0.015`. Default threshold
`COST_CHECK_THRESHOLD_USD = 5.00`, env-overridable via
`INGEST_COST_CHECK_THRESHOLD_USD`. A `--cost-check {fail,warn,off}` flag
controls behavior on trip; default `fail` raises `CostCheckTripped` before
the next phase.

Storage-only for V1 — R2 egress is zero, Class A op cost is one-time and
bounded, so leaving them out keeps the arithmetic honest. PR-A measured
per-game compressed sizes (zstd): landing 5.7 KB, boxscore 5.5 KB, PxP
15.9 KB; full game-level backfill projects to ~350 MB ≈ **$0.005/month**,
three orders of magnitude inside the $5/mo threshold. The default `fail`
mode is a tripwire, not a brake.

`cost_check.py` lives at `src/puckbunny/ingestion/cost_check.py` (one
level above `nhl/`) — sport-agnostic, since R2 cost arithmetic is the same
for any future sport's bronze.

**Revisit if.** A new R2 cost component becomes load-bearing (e.g., Class
B read ops at backtest scale once silver pulls bronze regularly), or
multi-sport bronze pushes the projection within an order of magnitude of
the ceiling.

### D11. Resumability granularity

**Decision.** Per-scope-unit dedupe, applied uniformly across loaders:

| Loader | Endpoints | scope_key | Skip if | On miss |
|--------|-----------|-----------|---------|---------|
| games (via `DailyLoader`) | landing, boxscore, play-by-play | `str(game_id)` | All 3 manifest entries present | Re-fetch all 3 |
| team-season | roster, club-schedule-season | `f"{season}\|{team}"` | Both entries present | Re-fetch both; on per-endpoint 404, write manifest entry only for the success |
| season-summaries | skater-summary, goalie-summary, team-summary | `format_season_id(season)` | All 3 entries present | Re-fetch all 3 |

Per-endpoint dedupe was considered and rejected (rare-partial-failure
savings on the order of tens of fetches per backfill; logic divergence
between daily and backfill not worth it). Manifest schema stays
per-endpoint, so a future ADR can shift to per-endpoint dedupe without a
data migration.

**404 log-and-skip on team-season.** When `TeamSeasonLoader.load_one`
returns `None` for one or both endpoints (404 on an invalid
`(season, team)` pair), the orchestrator writes manifest entries only
for the endpoints that succeeded. Subsequent runs re-attempt the 404
endpoint (one wasted fetch per invalid pair per run, bounded by
`team_abbrevs`). Keeps the manifest's `ok`-writes-only invariant intact.

**Revisit if.** Real evidence shows partial-failure waste matters — at
which point flip to per-endpoint dedupe under the existing schema.

### D12. Season-summaries `gameTypeId` filter

**Decision.** Don't filter season-summaries fetches by `gameTypeId`. One
GET per `(endpoint, season)` at `cayenneExp=seasonId={S}&limit=-1`,
storing the combined regular+playoff aggregate verbatim in bronze. The
PR-F0 spike confirmed that for finalized seasons the unfiltered response
pools regular and playoff games (so e.g. Washington Capitals 2024-25 lands
with `gamesPlayed=92` once playoffs conclude). Silver knows the aggregate
is combined and doesn't try to decompose.

Alternatives considered: two fetches per season with
`gameTypeId=2`/`gameTypeId=3` filters, or three fetches (combined +
regular-only + playoff-only). The doubled-fetch path is straightforward
under the existing manifest (`scope_key = f"{season}|gtype={gtype}"`) and
doubles request count to ~22 across the backfill — trivial. We took the
cheap path because M2 has no consumer that needs the decomposition.

**Revisit if.** M4 modeling surfaces a need for regular-season-only
player priors (or playoff-only ones) — flip to the two-fetch path under
the existing manifest schema, no migration required.

## Operational notes

These aren't decisions but are durable facts the loaders encode and a
future contributor would otherwise have to reverse-engineer.

**Franchise events in `team_abbrevs(season)`.** The team-season loader
enumerates the active NHL franchises for a given season via
`team_abbrevs(season)`, built from a 30-team
`_BASE_TEAM_ABBREVS_2015_2017` set plus three franchise events:

- **2017-18+**: VGK (Vegas Golden Knights, expansion) — 31 teams.
- **2021-22+**: SEA (Seattle Kraken, expansion) — 32 teams.
- **2024-25+**: ARI relocates to UTA (Utah Hockey Club). Drop ARI, add
  UTA — 32 teams.

Multi-sport expansion in Phase 3 will need an equivalent
franchise-event ledger per league; this is the load-bearing invariant
behind avoiding spurious 404s on `(season, team)` pairs that never
existed.

**Manifest-write responsibility split.** `DailyLoader` writes manifest
entries internally — the games phase composes by calling `load_date(date)`
and letting it handle everything. `TeamSeasonLoader` and
`SeasonSummariesLoader` are cadence-agnostic (see the parked
`*-cadence-gating.md` docs); they don't touch the manifest. The backfill
orchestrator owns gating before the call and `manifest.append_many(...)`
after, with append granularity of one batch per scope unit.

## Consequences

**Positive.**

- Bronze is reproducible: every byte in `bronze/nhl_api/` is recoverable
  from the manifest plus the source API, and re-parses are free (no
  re-fetch needed). PR-A's storage measurements confirm we sit
  comfortably inside the M2 cost ceiling.
- Daily and backfill share a single code path, so the rot surface is one
  thing to maintain.
- The decisions are sport-agnostic at the layers above NHL specifics
  (bronze layout, manifest, cost-check, package name) — adding MLB or
  another sport is new loaders, not a rewrite.

**Negative.**

- Storing `response_json` verbatim in every bronze row roughly doubles
  bronze size versus a typed-column-only shape; we paid that bill
  deliberately for schema-drift recovery, but it shows up in every cost
  projection.
- Per-scope-unit dedupe re-fetches sibling endpoints on rare partial
  failures. Bounded waste, but real.
- Single-process manifest writer is a known M10 cliff. The append-only
  JSONL shape doesn't survive concurrent writers as-is.

**Neutral.**

- The `--loader` taxonomy in the backfill CLI is calibrated to M2's
  three loaders. Adding M4 odds will likely either extend this list or
  retire the CLI in favor of Dagster assets — both are acceptable
  trajectories.

## Cross-references

- [`docs/milestones/m2-nhl-ingestion.md`](../milestones/m2-nhl-ingestion.md) —
  long-form reasoning for D1–D11 and the PR-A through PR-G work breakdown.
- [`docs/architecture/data-warehouse.md`](../architecture/data-warehouse.md) —
  bronze layout in the broader warehouse architecture.
- [`docs/infrastructure/r2.md`](../infrastructure/r2.md) — R2 bucket
  provisioning runbook.
- ADR-0001 — warehouse stack (R2 + DuckDB/MotherDuck + dbt). ADR-0003
  sits inside that envelope on the ingestion side.
