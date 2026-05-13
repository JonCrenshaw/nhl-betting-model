# M3 — Silver Layer & Sport-Agnostic Schema

**Status.** Not started. M2 complete; M3 is the active next milestone.
**Roadmap line.** `M3 | Silver layer & sport-agnostic schema | 3 weeks` (revised from 2 during M2 close planning session, May 2026).
**Prerequisites met.** M2 complete on `main`. Bronze Parquet in R2 (`puckbunny-lake`). dbt-core + dbt-duckdb in `pyproject.toml`. Scaffold in `dbt/`.

---

## Objective

Build the silver layer: parse bronze Parquet from R2 into conformed, sport-agnostic dbt models using DuckDB. The result is a queryable silver layer — `dim_` and `fct_` tables in MotherDuck — that M4 (odds), M5 (features), and all downstream milestones consume without touching bronze directly.

The silver schema must be sport-agnostic from day one. NHL-specific field names are a bug above the staging layer.

---

## Exit criteria

From `docs/roadmap.md`:

- `dim_sport`, `dim_league` — seed tables (NHL + ice_hockey for now; schema generalizes to any sport).
- `dim_team` — conformed team dimension, one row per team per league, NHL abbreviations mapped to universal IDs.
- `dim_player` — conformed player dimension, one row per player, derived from roster + boxscore.
- `fct_game` — game spine with datetime, home/away team FKs, status.
- `fct_game_outcome` — final scores, regulation/OT/SO flags.
- `fct_game_event` — sport-agnostic event table from play-by-play (shots, goals, penalties, faceoffs, hits, period markers).
- `fct_game_lineup` — per-player per-game: who played, position, TOI, skater/goalie stat context.
- `dim_market` and `fct_odds_snapshot` explicitly **deferred to M4** (no odds data in bronze yet).
- dbt tests passing: unique + not_null on every PK; referential integrity on all FK columns; CI green.
- MotherDuck provisioned; `dbt run --target prod` succeeds against MotherDuck (same models, same tests).

---

## Decisions

### D1. Exit criteria scope — market and odds deferred to M4

The roadmap originally listed `market` and `odds` in M3's exit criteria. `dim_market` and `fct_odds_snapshot` require odds data from The Odds API, which isn't ingested until M4. They are removed from M3 scope and will be built in M4 alongside odds ingestion.

**Revisit if.** An interim need for market-schema objects arises before M4 (unlikely — nothing in M3 through M4's plan needs them).

### D2. fct_game_event (PxP) — included in M3

Three options were considered: include PxP in M3, defer to M5, or include only shots+goals. Full PxP staging is included in M3 because:
1. The data is already in bronze; excluding it would leave a gap between what's available and what's modeled.
2. M5 feature engineering (xG, shot quality, Corsi/Fenwick) needs `fct_game_event`; deferring forces M5 to do its own silver work, which is a scope leak.
3. A two-phase approach (basic now, full later) adds schema versioning complexity without a clear payoff.

The PxP bronze carries 15–20 event types; three structural types (`period-start`, `period-end`, `game-end`) carry no `details` block — silver uses nulls for those fields, consistent with the ADR-0003 D3 note. This adds one week to the estimate (2 weeks → 3 weeks).

**Revisit if.** PxP parsing proves more complex than anticipated mid-milestone; descope the `details` sub-types to M5 and ship the event spine only.

### D3. dbt folder structure — models/core/ for silver tables

The existing dbt scaffold configured three layers: `staging/` (views), `intermediate/` (ephemeral), `marts/` (tables). The CLAUDE.md naming conventions (`dim_`, `fct_`, `mart_`) imply four tiers: staging → intermediate → silver core → gold marts. `dim_` and `fct_` tables belong in silver, not in `marts/` (which is reserved for the gold consumer-facing layer per CLAUDE.md).

**Decision.** Add `models/core/` as the silver layer, materialized as tables in a `core` schema. `dbt_project.yml` updated in this plan; the `core/` folder is created in PR-A.

Folder layout after M3:
```
dbt/models/
├── staging/
│   └── nhl/              # stg_nhl__<endpoint> — one per bronze endpoint family
├── intermediate/         # int_nhl__<purpose> — dedup, spine-building, unnesting
├── core/                 # dim_* and fct_* — silver, sport-agnostic
└── marts/                # mart_* — gold, model-ready (M5+)
```

**Revisit if.** A fifth layer proves necessary (e.g., a `snapshot/` layer for slowly-changing dims). Add it to `dbt_project.yml` at that point.

### D4. MotherDuck provisioned as M3 prerequisite

M2 had R2 provisioning as a blocker before PR-A landed. M3's equivalent is MotherDuck: `dbt run --target prod` must work before the milestone closes. Provisioning cost is ~$10/month (within the $50/month V1 ceiling). The `profiles.yml.example` already defines both `dev` (local DuckDB) and `prod` (MotherDuck) targets.

Jon provisions MotherDuck and captures the steps in `docs/infrastructure/motherduck.md` (mirrors `docs/infrastructure/r2.md`). PR-A includes the runbook; MotherDuck provisioning is a kickoff blocker exactly as R2 was for M2.

**Revisit if.** MotherDuck pricing changes, or self-hosted DuckDB on a VM becomes cheaper once a VM is already running for Dagster (M10). At M10 planning, evaluate whether to keep MotherDuck or move to a VM.

### D5. ADR-0001 flipped to Accepted

ADR-0001 (warehouse stack: R2 + DuckDB/MotherDuck + dbt) was written as "Proposed" pre-implementation. M2 shipped the R2 + Python stack; M3 adds the dbt + DuckDB + MotherDuck side. ADR-0001 is flipped to `Accepted` in PR-A of this milestone — it is now the operating decision, not a proposal.

### D6. Staging layer convention for bronze JSON parsing

Each bronze row stores `response_json` (verbatim API body) as a string. Staging models parse this using DuckDB's native JSON functions. Established conventions for M3:

- Primary extraction: `json_extract_string(response_json, '$.field')` for scalars; `json_extract(response_json, '$.array')` for nested structures.
- Deduplication: each staging model deduplicates on its natural key (e.g., `game_id`, `season + team_abbrev`) using `qualify row_number() over (partition by <key> order by fetched_at_utc desc) = 1`. Takes the latest ingest per scope unit.
- Unnesting PxP events: `unnest(json_extract(response_json, '$.plays')::json[])` in the intermediate layer, not staging. Staging for play-by-play returns one row per game (same as bronze); intermediate unnests into one row per event.

This convention is documented here and in the staging model header comments.

---

## Architecture

### Staging models (`models/staging/nhl/`)

One staging view per bronze endpoint family. Naming: `stg_nhl__<endpoint_slug>` (underscores, no hyphens).

| Staging model | Bronze source | Natural key | Purpose |
|---|---|---|---|
| `stg_nhl__landing` | `bronze/nhl_api/landing/` | `game_id` | Game summary, final score, teams, game type |
| `stg_nhl__boxscore` | `bronze/nhl_api/boxscore/` | `game_id` | Per-player skater + goalie stats per game |
| `stg_nhl__play_by_play` | `bronze/nhl_api/play-by-play/` | `game_id` | Raw plays array (unnested in intermediate) |
| `stg_nhl__skater_summary` | `bronze/nhl_api/skater-summary/` | `season + player_id` | Season-level skater stats |
| `stg_nhl__goalie_summary` | `bronze/nhl_api/goalie-summary/` | `season + player_id` | Season-level goalie stats |
| `stg_nhl__team_summary` | `bronze/nhl_api/team-summary/` | `season + team_id` | Season-level team stats |
| `stg_nhl__roster` | `bronze/nhl_api/roster/` | `season + team_abbrev + player_id` | Roster membership |
| `stg_nhl__club_schedule_season` | `bronze/nhl_api/club-schedule-season/` | `season + team_abbrev` | Team's season schedule |

Each staging model:
1. Reads from the R2 Parquet partition using `read_parquet('s3://puckbunny-lake/bronze/nhl_api/<endpoint>/**/*.parquet', hive_partitioning=true)`.
2. Deduplicates on the natural key (latest `fetched_at_utc`).
3. Extracts typed columns from `response_json`; leaves `response_json` behind.
4. Carries `ingest_date` and `fetched_at_utc` as provenance columns.

### Intermediate models (`models/intermediate/`)

Dedup, spine-building, and unnesting transforms that aren't directly a silver entity but are needed to produce one.

| Intermediate model | Purpose |
|---|---|
| `int_nhl__game_events` | Unnest `stg_nhl__play_by_play` plays array → one row per event |
| `int_nhl__game_skater_stats` | Parse per-player skater rows from `stg_nhl__boxscore` |
| `int_nhl__game_goalie_stats` | Parse per-player goalie rows from `stg_nhl__boxscore` |
| `int_nhl__team_spine` | Unify team identifiers across endpoints; map NHL abbreviations |
| `int_nhl__player_spine` | Unify player identifiers across roster + boxscore appearances |

### Core silver tables (`models/core/`)

| Model | Type | Sourced from |
|---|---|---|
| `dim_sport` | seed | `dbt/seeds/dim_sport.csv` |
| `dim_league` | seed | `dbt/seeds/dim_league.csv` |
| `dim_team` | dim | `int_nhl__team_spine` |
| `dim_player` | dim | `int_nhl__player_spine` |
| `fct_game` | fct | `stg_nhl__landing` |
| `fct_game_outcome` | fct | `stg_nhl__landing` |
| `fct_game_event` | fct | `int_nhl__game_events` |
| `fct_game_lineup` | fct | `int_nhl__game_skater_stats`, `int_nhl__game_goalie_stats` |

Every core model has a YAML description. Every fact table has unique + not_null tests on its PK. Every FK column has a relationships test to its dim.

---

## Work breakdown (PR sequence)

**PR-A — Infrastructure + seeds + ADR-0001** (~2 days)
Kickoff blocker: MotherDuck provisioned by Jon before this PR opens.

- `docs/infrastructure/motherduck.md` — provisioning runbook (mirrors `docs/infrastructure/r2.md`): account setup, database creation, `MOTHERDUCK_TOKEN` env var, smoke test (`dbt debug --target prod`), cost posture (~$10/month), token rotation.
- `dbt/models/core/` folder created with a `README.md` placeholder.
- Seeds: `dbt/seeds/dim_sport.csv`, `dbt/seeds/dim_league.csv` with YAML descriptions and not_null tests.
- `dbt/dbt_project.yml` — `core/` layer materialization (already updated in the plan-session commit).
- Flip ADR-0001 `Proposed` → `Accepted` (already done in plan-session commit).
- `dbt debug --target dev` (local DuckDB) and `dbt debug --target prod` (MotherDuck) both green in CI or documented as verified locally.
- `dbt seed && dbt test --select dim_sport dim_league` green.

**PR-B — Staging layer** (~3 days)
Eight staging models, one per bronze endpoint. No intermediate or core models yet.

- `models/staging/nhl/stg_nhl__landing.sql` + YAML
- `models/staging/nhl/stg_nhl__boxscore.sql` + YAML
- `models/staging/nhl/stg_nhl__play_by_play.sql` + YAML
- `models/staging/nhl/stg_nhl__skater_summary.sql` + YAML
- `models/staging/nhl/stg_nhl__goalie_summary.sql` + YAML
- `models/staging/nhl/stg_nhl__team_summary.sql` + YAML
- `models/staging/nhl/stg_nhl__roster.sql` + YAML
- `models/staging/nhl/stg_nhl__club_schedule_season.sql` + YAML
- DuckDB JSON extraction patterns established (see D6).
- Tests: not_null on natural keys; `accepted_values` on `game_state` and `game_type`.
- `dbt run --select staging && dbt test --select staging` green.

Working order: `landing` first (simplest structure), then `boxscore`, then the rest. `play_by_play` last (largest, most complex raw shape).

**PR-C — dim_team + dim_player** (~2 days)
- `models/intermediate/int_nhl__team_spine.sql` — unify team name + abbreviation across endpoints; handle franchise events (VGK 2017–18, SEA 2021–22, ARI→UTA 2024–25); generate a stable `team_id`.
- `models/core/dim_team.sql` + YAML — sport/league FKs, `external_ids` JSON, arena, geography columns nullable for now.
- `models/intermediate/int_nhl__player_spine.sql` — union roster + boxscore appearances, deduplicate on `player_id`.
- `models/core/dim_player.sql` + YAML — position, shoots/catches, birth_date, `external_ids`.
- Tests: unique + not_null on `team_id`, `player_id`; relationships to `dim_league`.

**PR-D — fct_game + fct_game_outcome** (~1.5 days)
- `models/core/fct_game.sql` + YAML — game spine: `game_id`, `league_id`, `season`, `game_datetime_utc`, `home_team_id`, `away_team_id`, `venue_team_id`, `game_type` (regular/playoff), `status`.
- `models/core/fct_game_outcome.sql` + YAML — `home_goals`, `away_goals`, `winning_team_id`, `period_end` (`REG`/`OT`/`SO`), derived `home_win` boolean.
- Tests: unique + not_null on `game_id`; relationships from team FKs to `dim_team`.

**PR-E — fct_game_event (PxP)** (~2 days)
- `models/intermediate/int_nhl__game_events.sql` — unnest plays array from `stg_nhl__play_by_play`; one row per event; parse `typeCode`, `periodDescriptor`, `timeInPeriod`, coordinate fields, player participant IDs.
- `models/core/fct_game_event.sql` + YAML — sport-agnostic columns: `event_id`, `game_id`, `period`, `period_time_elapsed_s`, `event_type` (mapped from NHL type codes to generic vocabulary: `shot`, `goal`, `penalty`, `faceoff`, `hit`, `blocked_shot`, `period_start`, `period_end`, `game_end`), `x_coord`, `y_coord`, `team_id`, `primary_player_id`, `secondary_player_id`, `details_json` (remaining event-specific fields).
- Three structural events with no `details` block (`period-start`, `period-end`, `game-end`) get null coordinates and player IDs — documented in YAML.
- Tests: unique on `event_id`; not_null on `game_id`, `event_type`, `period`.

**PR-F — fct_game_lineup** (~1.5 days)
- `models/intermediate/int_nhl__game_skater_stats.sql` — parse `playerByGameStats.forwards` + `playerByGameStats.defensemen` from boxscore; one row per `(game_id, player_id)`.
- `models/intermediate/int_nhl__game_goalie_stats.sql` — parse `playerByGameStats.goalies`; one row per `(game_id, player_id)`.
- `models/core/fct_game_lineup.sql` + YAML — union skaters + goalies; columns: `game_id`, `team_id`, `player_id`, `position_type` (`F`/`D`/`G`), `toi_s` (time on ice in seconds), `goals`, `assists`, `shots`, `saves` (null for skaters), `goals_against` (null for skaters). Line/pairing assignments are not available from M2 bronze; add if a future data source provides them.
- Tests: unique on `(game_id, player_id)`; not_null on `game_id`, `team_id`, `player_id`.

**PR-G — Docs + MotherDuck smoke + milestone close** (~1 day)
- Refresh `docs/architecture/data-warehouse.md`: silver section updated to "as-built" (table list, as-of date).
- `docs/milestones/m3-silver-layer.md` status line updated to Complete.
- Verify `dbt run --target prod && dbt test --target prod` succeeds against MotherDuck (end-to-end prod smoke).
- Update `docs/roadmap.md` M3 → ✅ Complete.

---

## Risks and mitigations

1. **PxP event parsing complexity.** The NHL PxP API has 15–20 event types with divergent `details` shapes; new event types have appeared between seasons. Mitigation: `details_json` column preserves the raw sub-object so downstream consumers can extend parsing without re-ingesting. If specific event types block the PR, defer their `details` parsing to M5 while keeping the event spine (D2 revisit trigger).

2. **DuckDB JSON performance on large PxP partitions.** A full backfill (10+ seasons × ~1,300 games) will produce a large `fct_game_event` table. DuckDB handles this well, but the initial `dbt run` on the full dataset may be slow. Mitigation: develop against a single-season slice; benchmark full-run time before declaring prod ready; add `limit` scaffolding during development (`--vars '{"dev_limit": 1}'`).

3. **Team identity across franchise events.** ARI→UTA (2024–25), VGK expansion (2017–18), SEA expansion (2021–22) all fall within the backfill window. `int_nhl__team_spine` must handle these; careless deduplication creates phantom teams. Mitigation: hardcode franchise event mapping table (seed or inline CTE) in `int_nhl__team_spine`; test expected team count per season.

4. **MotherDuck cold start.** First `dbt run --target prod` against MotherDuck will download all bronze Parquet from R2 and materialize silver tables. Cold-start time could be 30–60 minutes for the full backfill. Not a blocker, but Jon should expect it. Subsequent runs are incremental.

5. **R2 credentials in dev.** Local DuckDB `dev` target reads Parquet from R2 via httpfs, which requires `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` in the environment. Developers who don't have these set get empty staging views. Mitigation: document in the MotherDuck runbook and in a `docs/development.md` note; alternatively, provide a local fixture Parquet for CI.

6. **ADR needed if silver schema changes mid-milestone.** The entity model in `docs/architecture/data-warehouse.md` is the design contract. If a table's shape must change structurally (e.g., splitting `fct_game_outcome` into separate tables, changing the event_type vocabulary), write a decision note in the PR description — a full ADR only if the change affects downstream consumers or would surprise a future session.

---

## Dependencies and cost check

- **MotherDuck provisioning** is the single infra blocker; must happen before PR-A merges. Estimated 15 minutes + ~10 min smoke test.
- **Running cost.** M3 adds MotherDuck (~$10/month) to the run-rate. Total V1 run-rate rises to ~$12–15/month — well inside the $50/month ceiling.
- **No new paid data sources at M3.** The historical-odds purchase remains an M4 item.
