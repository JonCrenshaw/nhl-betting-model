# M2 — NHL API Ingestion

**Status.** Draft. Awaiting Jon's review.
**Roadmap line.** `M2 | NHL API ingestion | 2–3 weeks`
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

**Recommendation: `api-web.nhle.com` + `api.nhle.com/stats/rest/v1` as primary, no fallback built.**

The legacy `statsapi.web.nhl.com` was effectively deprecated in 2023 when NHL.com migrated to the modern endpoints. Committing to the modern surface avoids building a shim layer for a deprecated API. The PR-A spike (below) confirms whether the modern surface covers the historical depth we need (target: 2015–16 season onward). If a specific endpoint is only on the legacy surface, we add a narrow, one-off pull and document it in ADR-0003.

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

---

## Architecture

```
src/puckbunny/
├── __init__.py
├── config.py                       # pydantic-settings: env + defaults
├── logging_setup.py                # structlog JSON config
├── storage/
│   ├── __init__.py
│   ├── r2.py                       # S3-compatible client (boto3 or s3fs)
│   └── parquet.py                  # pyarrow write + partition helpers
├── http/
│   ├── __init__.py
│   └── client.py                   # rate-limited httpx + tenacity retries
└── ingestion/
    ├── __init__.py
    ├── manifest.py                 # ingest_runs.jsonl read/write
    └── nhl/
        ├── __init__.py
        ├── endpoints.py            # URL + param builders
        ├── schemas.py              # pydantic models for response shapes
        ├── games.py                # landing + boxscore per gameId
        ├── play_by_play.py         # PxP per gameId
        ├── schedule.py             # day / season discovery
        ├── season_summaries.py     # skater / goalie / team summaries
        ├── roster.py               # team rosters by season
        └── cli.py                  # `python -m puckbunny.ingestion.nhl ...`

tests/
├── ingestion/
│   ├── cassettes/                  # recorded responses (pytest-recording)
│   ├── test_http_client.py
│   ├── test_nhl_games.py
│   ├── test_nhl_pbp.py
│   ├── test_schedule.py
│   ├── test_manifest.py
│   └── test_smoke_integration.py   # marker: integration
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

`api.nhle.com/stats/rest/v1`:

- `/skater/summary?cayenneExp=seasonId={SEASON}` — season-level skater stats.
- `/goalie/summary?cayenneExp=seasonId={SEASON}` — season-level goalie stats.
- `/team/summary?cayenneExp=seasonId={SEASON}` — team-level season stats.

Exact URL shapes and pagination behavior are finalized in PR-A.

---

## Work breakdown (PR sequence)

Each PR is independently reviewable and mergeable.

**PR-A — Spike: one-game end-to-end** (~1 day, throwaway branch)
Fetch one recent game's landing + boxscore + PxP against live API, write to local Parquet, sanity-check shape and volume. Output: a short notes doc + any surface-level deviations from this plan. De-risks PR-B through PR-E.

**PR-B — HTTP client + storage primitives** (~2 days)
`http/client.py` (rate limiter + retries), `storage/r2.py`, `storage/parquet.py`, `config.py`, `logging_setup.py`. Tests use cassettes and a local-filesystem Parquet target. No NHL-specific code.

**PR-C — NHL games endpoint (landing + boxscore)** (~2 days)
`ingestion/nhl/games.py`, `schemas.py`, and the typed-envelope Parquet writer. Pydantic models for expected response shape. Cassette tests. CLI: `uv run python -m puckbunny.ingestion.nhl games --game-id <id>`.

**PR-D — Play-by-play loader** (~1.5 days)
`ingestion/nhl/play_by_play.py` built on PR-C primitives. PxP is the largest payload per game; validates the bronze layout works for volume.

**PR-E — Schedule + daily incremental** (~2 days)
`ingestion/nhl/schedule.py`. CLI: `uv run python -m puckbunny.ingestion.nhl daily [--date YYYY-MM-DD]` (defaults to yesterday in America/Toronto). Walks schedule, fetches only `FINAL` games not yet in manifest. End-to-end smoke test covers the full flow.

**PR-F — Season-scoped loaders** (~2 days)
`season_summaries.py` + `roster.py`. Separate from game-level because rate of change is "once per season," not "once per day."

**PR-G — Backfill CLI + manifest** (~1 day)
`uv run python -m puckbunny.ingestion.nhl backfill --from-season 2015-16 --to-season 2025-26`. Uses manifest to resume after interruption. Cost-check step at end: log bytes written and projected monthly R2 cost.

**PR-H — Docs + ADR-0003** (~0.5 day)
ADR-0003 "NHL API surface and bronze shape" captures D1–D4 with revisit triggers. Update `docs/architecture/data-warehouse.md` if PR-A surfaced changes. Add `docs/infrastructure/r2.md` covering bucket setup.

**Estimate.** 11 working days ≈ 4 calendar weeks at ~10 hrs/week. Roadmap originally called 2–3 weeks; **M2 is extended to 4 weeks** so PR-F (season-scoped loaders) stays in scope. Reflected in roadmap.md as a single-line update at kickoff.

---

## Risks and mitigations

1. **NHL API schema drift mid-backfill.** Storing `response_json` verbatim in bronze means we can re-parse at any time without re-fetching. Mitigated.
2. **Rate limiting / ban.** Conservative default (2 req/sec), honest `User-Agent`, exponential backoff. If NHL starts 403'ing us we pause and re-evaluate before retrying.
3. **CI flake from integration tests.** All live-API tests are marked `@pytest.mark.integration` and excluded from default CI. A nightly CI job (later, not M2) can run them.
4. **R2 cost surprise.** End-of-backfill step logs bytes/file counts and monthly projection; alert threshold at $5/mo. PxP at ~13k games × ~100 KB each is ~1.3 GB — well inside the $5 ceiling.
5. **Leakage into silver assumptions.** Bronze is source-shaped by design (`nhl_api/...` in the path is intentional). Silver-layer sport-agnosticism is an M3 concern; M2 should not pre-optimize.
6. **Secret leakage.** R2 credentials via `.env` (gitignored). `gitleaks` CI job already catches committed secrets; the parked local hook (`docs/ideas/gitleaks-local-hook.md`) is not a blocker.

---

## Dependencies and cost check

- **Cloudflare R2 bucket provisioning** is the single infra blocker; needs to happen before PR-B is merged. Estimated 15 minutes.
- **Running cost.** M1 run-rate is $0. M2 adds ~$3/mo R2 storage, well inside the $50/mo Phase 1 ceiling.
- **One-time.** No paid data sources at M2. The historical-odds purchase (~$200–500) is an M4 item.

---

## Kickoff prerequisites (Jon)

The only remaining infrastructure step is provisioning Cloudflare R2 and getting credentials into `.env`. Steps below.

### R2 bucket provisioning — step by step

**Why R2.** ADR-0001 chose Cloudflare R2 for object storage because it's S3-compatible (so anything that talks S3 works), priced at ~$0.015/GB/month, and — critically — has zero egress fees, which is what makes DuckDB-over-Parquet economical for backtests.

**Estimated time.** 15–20 minutes, all in the Cloudflare dashboard. No CLI required.

**1. Cloudflare account.** If you don't already have one, sign up at <https://dash.cloudflare.com/sign-up>. The free tier is fine; R2 is billed separately and has its own free allowance (10 GB storage, 1M Class A ops, 10M Class B ops per month) which we'll stay inside for M2.

**2. Enable R2.** In the Cloudflare dashboard, click **R2 Object Storage** in the left sidebar. First-time use will prompt you to add a payment method even to use the free tier — this is normal. No charges accrue until you exceed the free allowance.

**3. Create the bucket.** Click **Create bucket**.

- Name: `puckbunny-lake`. (Note: I'm renaming from the `nhl-bet-lake` placeholder in `data-warehouse.md` to match the package name. Bucket names are global within an account but not across accounts, so it's fine. PR-H updates the warehouse doc.)
- Location hint: **Automatic** is fine. If you want to pin it, **ENAM** (Eastern North America) is closest to most NHL data sources.
- Default storage class: **Standard**.
- Click **Create bucket**.

**4. Note the S3 API endpoint.** On the bucket overview page, expand **Settings** → **S3 API**. You'll see an endpoint URL of the form `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`. Copy this. The `<ACCOUNT_ID>` is also your Cloudflare account ID, visible top-right in the dashboard.

**5. Create an API token scoped to this bucket.** Cloudflare moves this around; current path (verified April 2026):

- Left sidebar → **Storage & databases** → **R2** to reach the R2 Overview page.
- On Overview, find the **API Tokens** card → click **Manage**.
- Click **Create API token**.

- Token name: `puckbunny-ingestion-local-jon`. Naming convention is `<purpose>-<environment>-<owner>` so we can revoke cleanly later.
- Permissions: **Object Read & Write**.
- Specify bucket: select **Apply to specific buckets only** and pick `puckbunny-lake`. Don't grant account-wide access — least privilege.
- TTL: leave as **Forever** for now; we rotate when M10 wires up Dagster Cloud and uses its own token.
- Click **Create API token**.

**6. Save the credentials immediately.** Cloudflare shows the secret access key **once**. You get four values:

- **Access Key ID** (looks like a 32-char hex string)
- **Secret Access Key** (longer hex string)
- **Endpoint** for S3 clients (`https://<ACCOUNT_ID>.r2.cloudflarestorage.com`)
- **Jurisdiction-specific endpoints** — ignore unless we later need EU-jurisdiction storage; not relevant for V1.

**7. Drop them into `.env`.** Create `D:\Git\PuckBunny\nhl-betting-model\.env` (file does not exist yet; `.gitignore` already excludes `.env` and `.env.*` except `.env.example`):

```dotenv
# Cloudflare R2 (S3-compatible)
R2_ACCOUNT_ID=<your account ID>
R2_ACCESS_KEY_ID=<from step 6>
R2_SECRET_ACCESS_KEY=<from step 6>
R2_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_BUCKET=puckbunny-lake
R2_REGION=auto

# Ingestion defaults (overridable per-invocation)
INGEST_RATE_LIMIT_PER_SEC=2
INGEST_USER_AGENT=PuckBunny/0.1 (contact: crenshaw.jonathan@gmail.com)
```

`R2_REGION=auto` is the magic value boto3 wants for R2; the actual region is server-determined.

**8. Commit a `.env.example`.** PR-B includes this file. It's the same shape as above with values blanked out so future contributors know which keys are required.

**9. Smoke-test the credentials.** Optional but worth doing before PR-B opens. Two quick options:

**Option A — `aws` CLI** (if you have it installed):
```powershell
aws s3 ls s3://puckbunny-lake/ `
  --endpoint-url https://<ACCOUNT_ID>.r2.cloudflarestorage.com `
  --region auto
```
Should return empty (no error).

**Option B — Python one-liner from the activated venv**:
```powershell
uv run python -c "import os, boto3; from dotenv import load_dotenv; load_dotenv(); s3 = boto3.client('s3', endpoint_url=os.environ['R2_ENDPOINT_URL'], aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto'); print(s3.list_buckets())"
```
Requires `boto3` and `python-dotenv` to be installed; both will land in PR-B as runtime deps. If you'd rather not pre-install, skip this step and the smoke test runs as part of PR-B's CI.

### Things to double-check before PR-A starts

- `.env` exists, `git status` confirms it's not tracked.
- Smoke test (step 9) returns `OK. Object count: 0`. This is the real gate — it proves the credentials work end-to-end.
- (Optional, nice-to-have) The token-creation email from Cloudflare arrived. Sometimes routed to spam or not sent at all on some account types; not a blocker if the smoke test passes.

Once those are green, PR-A is unblocked.

# M2 — NHL API Ingestion

**Status.** Draft. Awaiting Jon's review.
**Roadmap line.** `M2 | NHL API ingestion | 2–3 weeks`
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

**Recommendation: `api-web.nhle.com` + `api.nhle.com/stats/rest/v1` as primary, no fallback built.**

The legacy `statsapi.web.nhl.com` was effectively deprecated in 2023 when NHL.com migrated to the modern endpoints. Committing to the modern surface avoids building a shim layer for a deprecated API. The PR-A spike (below) confirms whether the modern surface covers the historical depth we need (target: 2015–16 season onward). If a specific endpoint is only on the legacy surface, we add a narrow, one-off pull and document it in ADR-0003.

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

---

## Architecture

```
src/puckbunny/
├── __init__.py
├── config.py                       # pydantic-settings: env + defaults
├── logging_setup.py                # structlog JSON config
├── storage/
│   ├── __init__.py
│   ├── r2.py                       # S3-compatible client (boto3 or s3fs)
│   └── parquet.py                  # pyarrow write + partition helpers
├── http/
│   ├── __init__.py
│   └── client.py                   # rate-limited httpx + tenacity retries
└── ingestion/
    ├── __init__.py
    ├── manifest.py                 # ingest_runs.jsonl read/write
    └── nhl/
        ├── __init__.py
        ├── endpoints.py            # URL + param builders
        ├── schemas.py              # pydantic models for response shapes
        ├── games.py                # landing + boxscore per gameId
        ├── play_by_play.py         # PxP per gameId
        ├── schedule.py             # day / season discovery
        ├── season_summaries.py     # skater / goalie / team summaries
        ├── roster.py               # team rosters by season
        └── cli.py                  # `python -m puckbunny.ingestion.nhl ...`

tests/
├── ingestion/
│   ├── cassettes/                  # recorded responses (pytest-recording)
│   ├── test_http_client.py
│   ├── test_nhl_games.py
│   ├── test_nhl_pbp.py
│   ├── test_schedule.py
│   ├── test_manifest.py
│   └── test_smoke_integration.py   # marker: integration
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

`api.nhle.com/stats/rest/v1`:

- `/skater/summary?cayenneExp=seasonId={SEASON}` — season-level skater stats.
- `/goalie/summary?cayenneExp=seasonId={SEASON}` — season-level goalie stats.
- `/team/summary?cayenneExp=seasonId={SEASON}` — team-level season stats.

Exact URL shapes and pagination behavior are finalized in PR-A.

---

## Work breakdown (PR sequence)

Each PR is independently reviewable and mergeable.

**PR-A — Spike: one-game end-to-end** (~1 day, throwaway branch)
Fetch one recent game's landing + boxscore + PxP against live API, write to local Parquet, sanity-check shape and volume. Output: a short notes doc + any surface-level deviations from this plan. De-risks PR-B through PR-E.

**PR-B — HTTP client + storage primitives** (~2 days)
`http/client.py` (rate limiter + retries), `storage/r2.py`, `storage/parquet.py`, `config.py`, `logging_setup.py`. Tests use cassettes and a local-filesystem Parquet target. No NHL-specific code.

**PR-C — NHL games endpoint (landing + boxscore)** (~2 days)
`ingestion/nhl/games.py`, `schemas.py`, and the typed-envelope Parquet writer. Pydantic models for expected response shape. Cassette tests. CLI: `uv run python -m puckbunny.ingestion.nhl games --game-id <id>`.

**PR-D — Play-by-play loader** (~1.5 days)
`ingestion/nhl/play_by_play.py` built on PR-C primitives. PxP is the largest payload per game; validates the bronze layout works for volume.

**PR-E — Schedule + daily incremental** (~2 days)
`ingestion/nhl/schedule.py`. CLI: `uv run python -m puckbunny.ingestion.nhl daily [--date YYYY-MM-DD]` (defaults to yesterday in America/Toronto). Walks schedule, fetches only `FINAL` games not yet in manifest. End-to-end smoke test covers the full flow.

**PR-F — Season-scoped loaders** (~2 days)
`season_summaries.py` + `roster.py`. Separate from game-level because rate of change is "once per season," not "once per day."

**PR-G — Backfill CLI + manifest** (~1 day)
`uv run python -m puckbunny.ingestion.nhl backfill --from-season 2015-16 --to-season 2025-26`. Uses manifest to resume after interruption. Cost-check step at end: log bytes written and projected monthly R2 cost.

**PR-H — Docs + ADR-0003** (~0.5 day)
ADR-0003 "NHL API surface and bronze shape" captures D1–D4 with revisit triggers. Update `docs/architecture/data-warehouse.md` if PR-A surfaced changes. Add `docs/infrastructure/r2.md` covering bucket setup.

**Estimate.** 11 working days ≈ 4 calendar weeks at ~10 hrs/week. Roadmap originally called 2–3 weeks; **M2 is extended to 4 weeks** so PR-F (season-scoped loaders) stays in scope. Reflected in roadmap.md as a single-line update at kickoff.

---

## Risks and mitigations

1. **NHL API schema drift mid-backfill.** Storing `response_json` verbatim in bronze means we can re-parse at any time without re-fetching. Mitigated.
2. **Rate limiting / ban.** Conservative default (2 req/sec), honest `User-Agent`, exponential backoff. If NHL starts 403'ing us we pause and re-evaluate before retrying.
3. **CI flake from integration tests.** All live-API tests are marked `@pytest.mark.integration` and excluded from default CI. A nightly CI job (later, not M2) can run them.
4. **R2 cost surprise.** End-of-backfill step logs bytes/file counts and monthly projection; alert threshold at $5/mo. PxP at ~13k games × ~100 KB each is ~1.3 GB — well inside the $5 ceiling.
5. **Leakage into silver assumptions.** Bronze is source-shaped by design (`nhl_api/...` in the path is intentional). Silver-layer sport-agnosticism is an M3 concern; M2 should not pre-optimize.
6. **Secret leakage.** R2 credentials via `.env` (gitignored). `gitleaks` CI job already catches committed secrets; the parked local hook (`docs/ideas/gitleaks-local-hook.md`) is not a blocker.

---

## Dependencies and cost check

- **Cloudflare R2 bucket provisioning** is the single infra blocker; needs to happen before PR-B is merged. Estimated 15 minutes.
- **Running cost.** M1 run-rate is $0. M2 adds ~$3/mo R2 storage, well inside the $50/mo Phase 1 ceiling.
- **One-time.** No paid data sources at M2. The historical-odds purchase (~$200–500) is an M4 item.

---

## Kickoff prerequisites (Jon)

The only remaining infrastructure step is provisioning Cloudflare R2 and getting credentials into `.env`. Steps below.

### R2 bucket provisioning — step by step

**Why R2.** ADR-0001 chose Cloudflare R2 for object storage because it's S3-compatible (so anything that talks S3 works), priced at ~$0.015/GB/month, and — critically — has zero egress fees, which is what makes DuckDB-over-Parquet economical for backtests.

**Estimated time.** 15–20 minutes, all in the Cloudflare dashboard. No CLI required.

**1. Cloudflare account.** If you don't already have one, sign up at <https://dash.cloudflare.com/sign-up>. The free tier is fine; R2 is billed separately and has its own free allowance (10 GB storage, 1M Class A ops, 10M Class B ops per month) which we'll stay inside for M2.

**2. Enable R2.** In the Cloudflare dashboard, click **R2 Object Storage** in the left sidebar. First-time use will prompt you to add a payment method even to use the free tier — this is normal. No charges accrue until you exceed the free allowance.

**3. Create the bucket.** Click **Create bucket**.

- Name: `puckbunny-lake` (matches `data-warehouse.md`). Bucket names are global within an account but not across accounts.
- Location hint: **Automatic** is fine. If you want to pin it, **ENAM** (Eastern North America) is closest to most NHL data sources.
- Default storage class: **Standard**.
- Click **Create bucket**.

**4. Note the S3 API endpoint.** On the bucket overview page, expand **Settings** → **S3 API**. You'll see an endpoint URL of the form `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`. Copy this. The `<ACCOUNT_ID>` is also your Cloudflare account ID, visible top-right in the dashboard.

**5. Create an API token scoped to this bucket.** Cloudflare moves this around; current path (verified April 2026):

- Left sidebar → **Storage & databases** → **R2** to reach the R2 Overview page.
- On Overview, find the **API Tokens** card → click **Manage**.
- Click **Create API token**.

- Token name: `puckbunny-ingestion-local-jon`. Naming convention is `<purpose>-<environment>-<owner>` so we can revoke cleanly later.
- Permissions: **Object Read & Write**.
- Specify bucket: select **Apply to specific buckets only** and pick `puckbunny-lake`. Don't grant account-wide access — least privilege.
- TTL: leave as **Forever** for now; we rotate when M10 wires up Dagster Cloud and uses its own token.
- Click **Create API token**.

**6. Save the credentials immediately.** Cloudflare shows the secret access key **once**. You get four values:

- **Access Key ID** (looks like a 32-char hex string)
- **Secret Access Key** (longer hex string)
- **Endpoint** for S3 clients (`https://<ACCOUNT_ID>.r2.cloudflarestorage.com`)
- **Jurisdiction-specific endpoints** — ignore unless we later need EU-jurisdiction storage; not relevant for V1.

**7. Drop them into `.env`.** Create `D:\Git\PuckBunny\nhl-betting-model\.env` (file does not exist yet; `.gitignore` already excludes `.env` and `.env.*` except `.env.example`):

```dotenv
# Cloudflare R2 (S3-compatible)
R2_ACCOUNT_ID=<your account ID>
R2_ACCESS_KEY_ID=<from step 6>
R2_SECRET_ACCESS_KEY=<from step 6>
R2_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_BUCKET=puckbunny-lake
R2_REGION=auto

# Ingestion defaults (overridable per-invocation)
INGEST_RATE_LIMIT_PER_SEC=2
INGEST_USER_AGENT=PuckBunny/0.1 (contact: crenshaw.jonathan@gmail.com)
```

`R2_REGION=auto` is the magic value boto3 wants for R2; the actual region is server-determined.

**8. Commit a `.env.example`.** PR-B includes this file. It's the same shape as above with values blanked out so future contributors know which keys are required.

**9. Smoke-test the credentials.** Optional but worth doing before PR-B opens. Two quick options:

**Option A — `aws` CLI** (if you have it installed):
```powershell
aws s3 ls s3://puckbunny-lake/ `
  --endpoint-url https://<ACCOUNT_ID>.r2.cloudflarestorage.com `
  --region auto
```
Should return empty (no error).

**Option B — Python one-liner from the activated venv**:
```powershell
uv run python -c "import os, boto3; from dotenv import load_dotenv; load_dotenv(); s3 = boto3.client('s3', endpoint_url=os.environ['R2_ENDPOINT_URL'], aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto'); print(s3.list_buckets())"
```
Requires `boto3` and `python-dotenv` to be installed; both will land in PR-B as runtime deps. If you'd rather not pre-install, skip this step and the smoke test runs as part of PR-B's CI.

### Things to double-check before PR-A starts

- `.env` exists, `git status` confirms it's not tracked.
- Smoke test (step 9) returns `OK. Object count: 0`. This is the real gate — it proves the credentials work end-to-end.
- (Optional, nice-to-have) The token-creation email from Cloudflare arrived. Sometimes routed to spam or not sent at all on some account types; not a blocker if the smoke test passes.

Once those are green, PR-A is unblocked.
