# M2 — NHL API Ingestion

**Status.** Active. PR-A through PR-G merged on `main`; PR-H (this doc refresh + ADR-0003) in flight as the milestone-close PR.
**Roadmap line.** `M2 | NHL API ingestion | 4 weeks` (revised from 2–3 at kickoff).
**Prerequisites met.** M1 complete on `main` (devcontainer, uv, dbt scaffold, CI).

---

## Objective

Land historical and daily NHL game, skater, goalie, and play-by-play data into bronze as partitioned Parquet in Cloudflare R2, driven by an incremental, idempotent loader. The loader is a plain `uv run` CLI for M2; it will be wrapped as a Dagster asset in M10 without a rewrite.

## Exit criteria

From `docs/roadmap.md`:

- Historical game, skater, goalie, and play-by-play data loaded into bronze.
- Incremental daily loader running end-to-end.
- Partitioned Parquet in object storage (Cloudflare R2, per ADR-0001).

Explicit quality gates so "done" is unambiguous:

- Every committed ingestion code path has unit tests against recorded HTTP cassettes.
- One smoke test per endpoint family runs against the live API, gated behind `@pytest.mark.integration`.
- CI green on every PR; integration tests excluded from default CI.
- `uv run python -m puckbunny.ingestion.nhl backfill --from-season 2015-16 --to-season 2025-26` completes end-to-end (may span multiple invocations via manifest-based resume).
- `uv run python -m puckbunny.ingestion.nhl daily` picks up only new-since-last-successful-run and exits clean on a no-new-games day.
- R2 monthly cost projection <$5 at full backfill scale, logged at end of each backfill batch.
- ADR-0003 committed documenting the API-surface and bronze-shape decisions.

---

## Open decisions and proposed answers

### D1. Which NHL API surface

**Recommendation: `api-web.nhle.com` + `api.nhle.com/stats/rest/en` as primary, no fallback built.**

The legacy `statsapi.web.nhl.com` was effectively deprecated in 2023 when NHL.com migrated to the modern endpoints. Committing to the modern surface avoids building a shim layer for a deprecated API. The PR-A spike (April 2026) confirmed the modern surface returns 200s for `landing`, `boxscore`, and `play-by-play` with the planned `User-Agent` and no auth, against a recent playoff game. Historical depth (2015–16 onward) is verified opportunistically as PR-G backfills; if a specific endpoint is only on the legacy surface, we add a narrow, one-off pull and document it in ADR-0003. (Durable record: [ADR-0003 D1](../decisions/0003-nhl-api-surface-and-bronze-shape.md#d1-nhl-api-surface).)

### D2. Bronze partitioning scheme

**Recommendation: `bronze/nhl_api/{endpoint}/ingest_date=YYYY-MM-DD/*.parquet`.**

Matches the sketch already in `docs/architecture/data-warehouse.md`. Rationale:

- `ingest_date` is the reproducibility key — reproducing a model at time T means reading only partitions with `ingest_date <= T`.
- Season is a column inside the payload, not a partition key. Cross-season queries stay simple and we never have to re-partition.
- Partitioning by endpoint separates hot write paths (daily games, PxP) from cold ones (historical rosters, season summaries).

### D3. Bronze payload shape

**Recommendation: "typed envelope plus raw JSON" per row.**

Each bronze row:

| Column | Type | Purpose |
|--------|------|---------|
| `game_id` or `entity_id` | int / str | Natural key for the payload |
| `season` | str (e.g. "20252026") | Filter / partition helper |
| `game_date` or `as_of_date` | date | Event date, not ingest date |
| `endpoint` | str | URL template that produced this row |
| `endpoint_params_json` | str | The exact parameter dict used |
| `fetched_at_utc` | timestamp | When we called the API |
| `response_json` | str | Verbatim API response body |
| `response_sha256` | str | Dedupe key for idempotent re-runs |

Typed columns make bronze queries fast and schema drift visible; `response_json` preserves the exact API payload so downstream parsing bugs or API schema drift are recoverable without re-fetching.

### D4. Historical backfill strategy

**Recommendation: one parameterized loader, invoked across seasons. No separate one-shot script.**

Backfill is `for season in range: loader.run(season=season)`. Same code path as daily ingest — the daily job is the only one that stays alive long enough to rot, and keeping paths unified means the rot surfaces in backfill too where we'll catch it.

Scope: 2015–16 season through current (~10 seasons × ~1,300 games + playoffs ≈ ~13k games). At 2 req/sec with 3 game-level endpoints per game, full PxP backfill is ~5–6 hours of wall time, easily chunked.

### D5. Loader location and Python package name

**Decided.** Package name is `puckbunny`. Location is `src/puckbunny/ingestion/nhl/`. Sport-agnostic, matches product name, keeps Phase 3 sports from living under an NHL-branded namespace. PR-B flips `package = false` off in `pyproject.toml` and adds an editable install of the new package.

### D6. Rate-limiting and retry posture

**Recommendation: 2 req/sec default (config-overridable), exponential backoff with jitter on 429/5xx, max 5 retries, total wall budget per request ≤60s.**

HTTP client: `httpx` (sync). Retry logic: `tenacity`. `User-Agent: PuckBunny/0.1 (contact: crenshaw.jonathan@gmail.com)` — polite and identifies us if NHL ever reaches out. Single-threaded for M2; parallelism comes with Dagster at M10.

### D7. Idempotency and resume semantics

**Recommendation: an append-only JSONL manifest in R2 at `bronze/_manifests/ingest_runs.jsonl`.**

One row per `(endpoint, scope)` successful fetch: `{run_id, endpoint, scope_key, fetched_at_utc, rows, bytes, status}`. Incremental mode reads the manifest to compute what's missing. Backfill also reads it to skip already-done work. No database yet — JSONL at this volume is fine and trivial to inspect.

### D8. Game discovery for backfill

**Recommendation: pure schedule day-walks via `DailyLoader.load_date(date)` for every calendar day in the season window.**

Three options were considered: (1) day-walks, reusing `DailyLoader` verbatim across `season_start..season_end` for each season; (2) a date set discovered from `club-schedule-season` after running the team-season phase first; (3) step-by-7 day-walks consuming the full week response per anchor date.

Day-walks win because the wall-time cost they pay is irrelevant: ~330 days × 11 seasons = ~3,600 schedule fetches at 2 req/sec ≈ 30 min, against ~5–6 hours of actual game-endpoint fetches that dominate the backfill. Empty days are no-ops in `DailyLoader` already (zero eligible games, no error). Option (2) is more elegant but couples the team-season and games phases into a strict order with shared state; option (3) introduces week-boundary edge cases (anchor day-of-week alignment, partial weeks at season ends) for an optimization that isn't load-bearing. Keeping the daily and backfill code paths identical also means PR-E's manifest-gating logic continues to be exercised by both jobs — same pattern, same failure modes.

Season date range hardcoded as Sept 1 of start year through June 30 of end year per season — covers preseason through Stanley Cup Final without needing a calendar lookup. Bronze ingests preseason games if the schedule returns them, consistent with Risk #5's "bronze is source-shaped"; silver M3 decides relevance.

### D9. Backfill subcommand layout

**Recommendation: a single `backfill` subcommand with a `--loader {games,season-summaries,team-season,all}` selector defaulting to `all`.**

```
uv run python -m puckbunny.ingestion.nhl backfill \
  --from-season 2015-16 --to-season 2025-26 \
  [--loader {games,season-summaries,team-season,all}] \
  [--cost-check {fail,warn,off}] \
  [--ingest-date YYYY-MM-DD] [--log-level …]
```

`--from-season` / `--to-season` accept either `YYYY-YY` (e.g. `2015-16`) or `YYYYYYYY` (e.g. `20152016`) — normalized via the existing `format_season_id` helper plus a small `parse_season_range` wrapper. **For consistency**, the existing `--season` flag on `team-season` and `season-summaries` should be extended in the same PR-G commit to accept both forms — small backwards-compatible win that prevents the CLI surface from splintering between subcommands. PR-G's PR description should call this out explicitly so it's reviewable.

`all` runs the loaders in this order so cheap, low-volume phases fail fast before burning hours on game-level fetches:

1. **team-season** — ~340 fetches, ~3 min wall.
2. **season-summaries** — ~33 fetches, ~30 sec wall.
3. **games** — ~5–6 hours wall, via `DailyLoader.load_date` for each date in the window.

Per-loader subcommands were considered and rejected: they multiply CLI surface for a use case (partial reruns) that's already covered by `--loader <name>`. Dispatch lives in Python, where stub-able factories exist, rather than in the shell where it would diverge from the existing test seam pattern.

### D10. Cost-check methodology

**Recommendation: end-of-loader-phase + end-of-overall checks against cumulative bronze size; default mode aborts above $5/mo projection.**

After each loader phase and once at end-of-overall, the orchestrator computes `bytes_cumulative` (sum across all manifest entries), projects monthly storage cost as `bytes_cumulative / 1024³ × $0.015`, and emits one structured `cost_check` log line. A `--cost-check {fail,warn,off}` flag (default `fail`) controls behavior when the projection exceeds `COST_CHECK_THRESHOLD_USD = 5.00`:

- `fail`: raise `CostCheckTripped` to abort before the next phase. Catches a real surprise (uncompressed dump, payload explosion, runaway loop) loud and early.
- `warn`: log at WARNING and continue.
- `off`: skip the check.

Threshold overridable via `INGEST_COST_CHECK_THRESHOLD_USD` env var for operators who want a tighter gate. Storage-only for V1: R2 egress is zero and Class A op cost is one-time and bounded, so leaving them out keeps the arithmetic honest and matches Risk #4's framing. PR-A's measurements project ~370 MB at full backfill scale ≈ **$0.0056/mo** — three orders of magnitude inside the ceiling, so the `fail` default is a tripwire, not a brake.

Module location is `src/puckbunny/ingestion/cost_check.py` (one level above `nhl/`) — sport-agnostic, since R2 cost arithmetic is the same for any future sport's bronze content.

### D11. Resumability granularity

**Recommendation: keep PR-E's per-scope-unit dedupe semantics and apply the same pattern to season-summaries and team-season.**

For each loader, "skip if all of its endpoints' manifest entries are present for this scope_key, else call `load_one(...)` and re-fetch all":

| Loader | Endpoints | scope_key | Skip if | On miss |
|--------|-----------|-----------|---------|---------|
| games (via `DailyLoader`) | landing, boxscore, play-by-play | `str(game_id)` | All 3 manifest entries present | Re-fetch all 3 (PR-E logic, untouched) |
| team-season | roster, club-schedule-season | `f"{season}\|{team}"` | Both manifest entries present | Re-fetch both; on per-endpoint 404, write manifest entry only for the success |
| season-summaries | skater-summary, goalie-summary, team-summary | `format_season_id(season)` | All 3 manifest entries present | Re-fetch all 3 |

Per-endpoint dedupe was considered: it would avoid the rare partial-failure case re-fetching sibling endpoints, saving on the order of tens of fetches per backfill run. Rejected because (i) it would diverge daily and backfill behavior on the same partial-failure case (the daily walker is per-game), (ii) it would force new partial-load methods on each loader (or duplicate calls inside the orchestrator), and (iii) the absolute cost saved is in the noise. Manifest schema stays per-endpoint, so a future ADR can shift to per-endpoint dedupe without a data migration if real evidence ever motivates it.

**404 log-and-skip on team-season.** When `TeamSeasonLoader.load_one` returns `None` for one or both endpoints (404 on an invalid `(season, team)` pair, e.g. `UTA` pre-2024-25), the orchestrator writes manifest entries only for the endpoints that succeeded. Subsequent runs re-attempt the 404 endpoint (one wasted fetch per invalid pair per run, bounded by `team_abbrevs`). Avoids polluting the manifest with skip-sentinels that would violate the "manifest records `ok` writes only" invariant.

**Manifest-write responsibility.** `DailyLoader` already writes manifest entries internally — the games phase composes by calling `load_date(date)` and letting it handle everything. For team-season and season-summaries (intentionally cadence-agnostic per the parked `*-cadence-gating.md` docs — they don't touch the manifest), the backfill orchestrator owns gating before the call and `manifest.append_many(...)` after. Append granularity is one batch per scope unit (per `(season, team)` for team-season, per season for season-summaries) — durable to mid-loop interruption while keeping PUT count low.

---

## Architecture

As-built after PR-A through PR-G (refreshed in PR-H):

```
src/puckbunny/
├── __init__.py
├── config.py                       # pydantic-settings: env + defaults
├── logging_setup.py                # structlog JSON config
├── storage/
│   ├── __init__.py
│   ├── base.py                     # storage interface
│   ├── local.py                    # local-filesystem implementation (tests)
│   ├── r2.py                       # S3-compatible client (boto3)
│   └── parquet.py                  # pyarrow write + partition helpers
├── http/
│   ├── __init__.py
│   └── client.py                   # rate-limited httpx + tenacity retries
└── ingestion/
    ├── __init__.py
    ├── cost_check.py               # sport-agnostic projection + threshold (PR-G)
    ├── manifest.py                 # ingest_runs.jsonl read/write
    └── nhl/
        ├── __init__.py
        ├── __main__.py             # python -m puckbunny.ingestion.nhl entrypoint
        ├── endpoints.py            # URL + param builders, team_abbrevs(season)
        ├── schemas.py              # pydantic models for response shapes
        ├── games.py                # landing + boxscore per gameId (PR-C)
        ├── play_by_play.py         # PxP per gameId (PR-D)
        ├── schedule.py             # ScheduleLoader + DailyLoader (PR-E)
        ├── season_summaries.py     # skater / goalie / team summaries (PR-F1)
        ├── team_season.py          # roster + club-schedule-season (PR-F2)
        ├── backfill.py             # orchestrator + phase functions (PR-G)
        └── cli.py                  # subcommand dispatch

tests/
├── conftest.py
├── test_config.py
├── test_logging_setup.py
├── http/
│   └── test_client.py
├── storage/
│   ├── test_local.py
│   ├── test_parquet.py
│   └── test_r2.py
└── ingestion/
    ├── test_manifest.py
    ├── test_cost_check.py          # PR-G
    ├── test_backfill.py            # PR-G orchestrator
    ├── test_backfill_resume.py     # PR-G end-to-end resume
    ├── test_nhl_endpoints.py
    ├── test_nhl_schemas.py
    ├── test_nhl_games.py
    ├── test_nhl_pbp.py
    ├── test_nhl_season_summaries.py
    ├── test_nhl_team_season.py
    ├── test_schedule.py
    └── test_smoke_integration.py   # marker: integration (live API)
```

### New runtime dependencies (pyproject.toml)

- `httpx` — HTTP client.
- `tenacity` — retries.
- `pydantic` + `pydantic-settings` — response validation and config.
- `structlog` — JSON logging.
- `pyarrow` — Parquet.
- `boto3` or `s3fs` — R2 (S3-compatible).
- `pytest-recording` (dev) — VCR cassettes for deterministic tests.

### Endpoints in scope for M2

`api-web.nhle.com`:

- `/v1/schedule/{YYYY-MM-DD}` — daily schedule; drives incremental loop.
- `/v1/gamecenter/{gameId}/landing` — game-level summary and final score.
- `/v1/gamecenter/{gameId}/boxscore` — per-player skater + goalie stats.
- `/v1/gamecenter/{gameId}/play-by-play` — event-level PxP.
- `/v1/club-schedule-season/{TEAM}/{SEASON}` — per-team season schedule for backfill discovery.
- `/v1/roster/{TEAM}/{SEASON}` — rosters.

`api.nhle.com/stats/rest/en` (note the mandatory `en` locale segment — `/v1/` is `api-web.nhle.com`'s convention, not this surface's; see PR-F0 spike notes):

- `/skater/summary?cayenneExp=seasonId={SEASON}&limit=-1` — season-level skater stats.
- `/goalie/summary?cayenneExp=seasonId={SEASON}&limit=-1` — season-level goalie stats.
- `/team/summary?cayenneExp=seasonId={SEASON}&limit=-1` — team-level season stats.

Exact URL shapes and pagination behavior are finalized in PR-A for the `api-web` endpoints and in PR-F0 ([`docs/ideas/prf-stats-rest-spike-notes.md`](../ideas/prf-stats-rest-spike-notes.md)) for the stats-rest endpoints.

---

## Work breakdown (PR sequence)

Each PR is independently reviewable and mergeable.

**PR-A — Spike: one-game end-to-end** ✅ *complete (April 2026, branch `spike/nhl-api-one-game`)*
Fetched one recent game's landing + boxscore + play-by-play against live API, wrote to local Parquet, sanity-checked shape and volume. Findings absorbed into [ADR-0003](../decisions/0003-nhl-api-surface-and-bronze-shape.md) in PR-H (D3 per-endpoint schemas, D8 `{FINAL, OFF}` state set, D10 measured storage projection); the actionable corrections were folded into PR-C/D/E and Risk #4 below. De-risked PR-B through PR-E.

**PR-B — HTTP client + storage primitives** ✅ *complete (April 2026, branch `feat/m2-pr-b-http-storage`)*
`http/client.py` (rate limiter + retries), `storage/r2.py`, `storage/parquet.py`, `config.py`, `logging_setup.py`. Tests use cassettes and a local-filesystem Parquet target. No NHL-specific code.

**PR-C — NHL games endpoint (landing + boxscore)** ✅ *complete (April 2026, branch `feat/m2-pr-c-games`)*
`ingestion/nhl/games.py`, `schemas.py`, and the typed-envelope Parquet writer. Pydantic models *per endpoint* (separate `LandingResponse` / `BoxscoreResponse` shapes — the three game-level endpoints overlap heavily but each has unique top-level fields, per spike notes §2). Cassette tests via committed JSON fixtures + ``httpx.MockTransport`` (functionally equivalent to the plan's pytest-recording recipe; see test module docstring). CLI: `uv run python -m puckbunny.ingestion.nhl games --game-id <id>`.

**PR-D — Play-by-play loader** ✅ *complete (April 2026, branch `feat/m2-pr-d-pbp`)*
`ingestion/nhl/play_by_play.py` built on PR-C primitives. PxP is the largest payload per game; validates the bronze layout works for volume. Pre-parser key scan confirmed coord/player-id presence on shooting events and faceoffs; three structural event types (`period-start`, `period-end`, `game-end`) carry no `details` block — silver (M3) treats those as known exceptions, bronze stays tolerant via `extra="allow"` on `PlayByPlayResponse`. (Durable record: [ADR-0003 D3](../decisions/0003-nhl-api-surface-and-bronze-shape.md#d3-bronze-payload-shape); PR-H absorbed the full scan output.) CLI: `uv run python -m puckbunny.ingestion.nhl play-by-play --game-id <id>`. Bronze partition `bronze/nhl_api/play-by-play/ingest_date=YYYY-MM-DD/`. Cassette tests via the same committed-JSON-fixture + `httpx.MockTransport` pattern PR-C established.

**PR-E — Schedule + daily incremental** ✅ *complete (April 2026, branch `feat/m2-pr-e-schedule`)*
`ingestion/nhl/schedule.py` (`ScheduleLoader` + `DailyLoader`) and `ingestion/manifest.py` (minimal append-only JSONL store at `bronze/_manifests/ingest_runs.jsonl`, per D7). CLI: `uv run python -m puckbunny.ingestion.nhl daily [--date YYYY-MM-DD] [--ingest-date YYYY-MM-DD]`. The `--date` default resolves to yesterday in America/Toronto via `zoneinfo` + the new `tzdata` runtime dep, so a morning UTC run picks up the previous Eastern slate even when the Eastern day boundary falls hours before UTC midnight. The walker iterates `gameWeek[*]` filtered to the target date, fetches only games whose `gameState ∈ {FINAL, OFF}` (constant `INGESTIBLE_GAME_STATES` in `endpoints.py`, per spike notes §1), and skips any game whose three game-level endpoints are already recorded in the manifest. End-to-end cassette test covers schedule + landing + boxscore + play-by-play in one flow; manifest dedupe is exercised both directions (skip when present, re-fetch when partial). Manifest entries are recorded per `(endpoint_template, game_id)` so PR-G's backfill can opt for per-endpoint dedupe without a schema change.

Idempotency tradeoff documented in the `schedule.py` module docstring: dedupe is at the *game* level — if any one of the three endpoints is missing for a game, all three are re-fetched. This trades a small amount of duplicate landing/boxscore writes (rare partial-failure case) for substantially simpler logic. Manifest still records per endpoint so PR-G isn't constrained.

**PR-F — Season-scoped loaders** (~3 days, split into F0/F1/F2)
Separate from game-level because rate of change is "once per season," not "once per day." Split into three sub-PRs at planning time after the PR-A pattern: an isolated spike to lock in the API contract, then per-loader implementation PRs.

- **PR-F0 — Spike: stats-rest probe** ✅ *complete (April 2026, branch `spike/m2-stats-rest-probe`)*
  Probed `api.nhle.com/stats/rest/en/{skater,goalie,team}/summary` against the live API. Findings in [`docs/ideas/prf-stats-rest-spike-notes.md`](../ideas/prf-stats-rest-spike-notes.md). Headlines: surface path is `/stats/rest/en/`, not `/v1/` (M2-doc correction folded in alongside this notes file); `limit=-1` returns the full result set in one GET (defensive `len(data) == total` assertion is the contract); unfiltered response pools regular + playoff aggregates for finalized seasons (`gameTypeId` filter decision deferred to ADR-0003 with revisit trigger). De-risks PR-F1; PR-F2 doesn't need its own spike since it lives on the `api-web.nhle.com` surface PR-A already validated.

- **PR-F1 — Season summaries** (~1.5 days)
  `season_summaries.py` covering `/skater/summary`, `/goalie/summary`, `/team/summary`. One GET per `(endpoint, season)` with `limit=-1`; per-endpoint pydantic row schemas; `scope_key = season` in the manifest. CLI: `uv run python -m puckbunny.ingestion.nhl season-summaries --season {SEASON}`. Cadence is weekly + post-Stanley-Cup-Final, NOT daily (per PR-F0 notes §6) — this loader is not wired into PR-E's daily walker.

- **PR-F2 — Roster + season schedule** ✅ *complete (May 2026, branch `feat/m2-pr-f2-team-season`)*
  `team_season.py` (renamed from the planned `roster.py` to follow PR-F1's "name for the scope, not for one endpoint" precedent — one loader covers both endpoints) on `api-web.nhle.com`. `TeamSeasonLoader.load_one(season, team)` hits `/v1/roster/{TEAM}/{SEASON}` and `/v1/club-schedule-season/{TEAM}/{SEASON}`, writes one envelope row per fetch, with per-endpoint log-and-skip on 404 (the spike-confirmed signal for "this `(team, season)` pair didn't exist"). One GET per `(endpoint, season, team)` with `scope_key = f"{season}|{team_abbrev}"` for the future PR-G manifest. CLI: `uv run python -m puckbunny.ingestion.nhl team-season --season SEASON [--team TEAM]`; default with `--team` omitted iterates `team_abbrevs(season)`. Defensive `currentSeason` invariant on the schedule endpoint via `ClubScheduleSeasonMismatchError`. Inline first-commit probe (no separate spike PR — surface was validated by PR-A and the unknowns were per-endpoint shape, not host); recorded fixtures committed to `tests/ingestion/fixtures/team_season/`. Findings in [`docs/ideas/prf2-spike-notes.md`](../ideas/prf2-spike-notes.md) — notably, the open-questions doc undercounted franchise events: VGK (2017-18) and SEA (2021-22) expansions also fall in the backfill window, alongside ARI→UTA (2024-25), so `team_abbrevs(season)` enumerates 30 / 31 / 32 / 32 across the four eras. M10 cadence design parked in [`docs/ideas/team-season-cadence-gating.md`](../ideas/team-season-cadence-gating.md) — three distinct schedules (backfill gated; weekly+trade-deadline-daily roster bypassing gating; post-schedule-release club-schedule gated). `format_season_id` and `normalize_team_abbrev` were renamed from their PR-F1 underscore-private form to public for cross-loader reuse.

**PR-G — Backfill CLI + manifest gating** (~1.5–2 days)
Branch: `feat/m2-pr-g-backfill`.

Decisions (D8–D11 above): pure schedule day-walks for game discovery; single `backfill` subcommand with a `--loader` selector; end-of-phase + end-of-overall cost checks with `--cost-check {fail,warn,off}` (default `fail`); per-scope-unit dedupe consistent with PR-E.

Modules added:

- `src/puckbunny/ingestion/nhl/backfill.py` — orchestrator. Three phase functions (`backfill_games`, `backfill_season_summaries`, `backfill_team_season`) plus a top-level `run_backfill(...)` that dispatches on `--loader`. Each phase: iterate scope units, gate via `manifest.has(...)` per the D11 table, call the loader's `load_one`, append manifest entries for successful endpoints, emit a phase-end cost-check.
- `src/puckbunny/ingestion/cost_check.py` — sport-agnostic projection + threshold logic. Exports `CostCheckTripped`, `COST_CHECK_THRESHOLD_USD`, `compute_projection(manifest, run_id) -> CostProjection`, `evaluate(projection, mode) -> None | raises`.
- `src/puckbunny/ingestion/nhl/endpoints.py` — small additions: `parse_season_range(from_season, to_season) -> list[str]` accepting `YYYY-YY` or `YYYYYYYY`; `dates_in_season(season) -> Iterator[date]` covering Sept 1 → June 30.
- `src/puckbunny/ingestion/nhl/cli.py` — new `backfill` subparser + `_cmd_backfill` + `_default_backfill_factory` matching the existing factory test seam (one factory builds the four collaborator instances: `DailyLoader`, `SeasonSummariesLoader`, `TeamSeasonLoader`, `ManifestStore`, sharing one `RateLimitedClient` so the rate-limit budget is process-wide).

Test surface (`tests/ingestion/`):

- `test_backfill.py` — orchestrator gating logic with stubbed loaders + a fake manifest. Covers all-present skip, any-missing fetch-and-record, team-season 404 write-only-the-success, `--loader` selector, season-range filtering, batch granularity.
- `test_cost_check.py` — projection arithmetic against synthetic manifest entries; `fail`/`warn`/`off` modes; env-var threshold override.
- `test_backfill_resume.py` — end-to-end against `LocalFilesystemStorage` + `httpx.MockTransport` cassette set. Tiny window (1 season, 2 dates, 2 teams). Asserts initial run produces expected bronze + manifest, repeat run is a no-op, partial-manifest delete re-fetches the affected scope unit only.
- `test_smoke_integration.py` — `@pytest.mark.integration` extension: one-season `season-summaries` backfill against the live API. Excluded from default CI.

Working order: orchestrator → cost_check → CLI wiring → unit tests → resume test → CLI smoke → manual one-season live-API smoke (not committed). The orchestrator is intentionally written before the CLI so the factory test seam falls out of the existing pattern rather than being designed under CLI pressure.

Out of scope for PR-G — explicitly:

- M10 cadence wiring. The bypass-gating Dagster assets parked in `docs/ideas/{season-summaries,team-season}-cadence-gating.md` are M10's problem; PR-G touches only the backfill side of those docs.
- Postponement detection (per `team-season-cadence-gating.md` "Trade-deadline override" / postponement notes). Re-arming a `club-schedule-season` manifest entry after a postponement is M10.
- Per-endpoint dedupe. D11 keeps the per-scope-unit pattern; revisit only if real evidence shows the rare-partial-failure waste is meaningful.
- ADR-0003. PR-H's job — D1–D11 will land in that ADR with revisit triggers.

**PR-H — Docs + ADR-0003** 🟡 *in flight (May 2026, branch `feat/m2-pr-h-adr-0003`)*
Milestone-close PR. ADR-0003 "NHL API surface and bronze shape" captures **D1–D12** with revisit triggers (D1–D7 from the original PR-A/B planning; D8–D11 the PR-G backfill/cost-check/dedupe shape; D12 the `gameTypeId` filter decision from the PR-F0 spike). Refreshed `docs/architecture/data-warehouse.md` (status flipped to "bronze implemented"; bronze tree reconciled with hyphenated partition slugs and `club-schedule-season`). Added `docs/infrastructure/r2.md` covering bucket setup, smoke tests, layout, cost posture, token rotation, and troubleshooting. Deleted `docs/ideas/pra-spike-notes.md` and `docs/ideas/prd-pbp-keys.md` once content was absorbed into ADR-0003.

**Doc-hygiene items deferred from PR-F1/F2/G** — folded in here:

- ✅ Architecture-diagram tree refreshed to match as-built `src/puckbunny/...` (replaces `roster.py` with `team_season.py`; adds `season_summaries.py`, `backfill.py`, `cost_check.py`, `storage/base.py`, `storage/local.py`; updates the `tests/` tree).
- ✅ "Endpoints in scope for M2" verified against as-built loader constants (`endpoints.py`).
- ✅ `_BASE_TEAM_ABBREVS_2015_2017` and `team_abbrevs(season)` franchise-event coverage (VGK / SEA / UTA) documented in ADR-0003 Operational Notes.

**Estimate.** 11 working days ≈ 4 calendar weeks at ~10 hrs/week. Roadmap originally called 2–3 weeks; **M2 is extended to 4 weeks** so PR-F (season-scoped loaders) stays in scope. Reflected in roadmap.md as a single-line update at kickoff.

---

## Risks and mitigations

1. **NHL API schema drift mid-backfill.** Storing `response_json` verbatim in bronze means we can re-parse at any time without re-fetching. Mitigated.
2. **Rate limiting / ban.** Conservative default (2 req/sec), honest `User-Agent`, exponential backoff. If NHL starts 403'ing us we pause and re-evaluate before retrying.
3. **CI flake from integration tests.** All live-API tests are marked `@pytest.mark.integration` and excluded from default CI. A nightly CI job (later, not M2) can run them.
4. **R2 cost surprise.** End-of-backfill step logs bytes/file counts and monthly projection; alert threshold at $5/mo. PR-A measured per-game compressed sizes (zstd): landing 5.7 KB, boxscore 5.5 KB, PxP 15.9 KB. Full game-level backfill projects to ~350 MB total ≈ **$0.005/month** storage — three orders of magnitude inside the ceiling, plus a one-time ~$0.20 in Class A ops during the initial backfill.
5. **Leakage into silver assumptions.** Bronze is source-shaped by design (`nhl_api/...` in the path is intentional). Silver-layer sport-agnosticism is an M3 concern; M2 should not pre-optimize.
6. **Secret leakage.** R2 credentials via `.env` (gitignored). `gitleaks` CI job already catches committed secrets; the parked local hook (`docs/ideas/gitleaks-local-hook.md`) is not a blocker.

---

## Dependencies and cost check

- **Cloudflare R2 bucket provisioning** is the single infra blocker; needs to happen before PR-B is merged. Estimated 15 minutes. *Done — bucket `puckbunny-lake` is provisioned and credentialed (April 2026).*
- **Running cost.** M1 run-rate is $0. M2 adds well under $1/mo R2 storage at full backfill scale (see Risk #4 for measured numbers), well inside the $50/mo Phase 1 ceiling.
- **One-time.** No paid data sources at M2. The historical-odds purchase (~$200–500) is an M4 item.

---

## Kickoff prerequisites (Jon)

Done. R2 bucket `puckbunny-lake` was provisioned and credentialed in April 2026, unblocking PR-A. The bucket-provisioning runbook moved to [`docs/infrastructure/r2.md`](../infrastructure/r2.md) in PR-H as a permanent operational doc (covers provisioning, smoke tests, layout, cost posture, token rotation, and troubleshooting).
