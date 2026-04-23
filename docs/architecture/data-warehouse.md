# Data Warehouse Architecture

Status: **Draft v1**. Supersedes nothing. Not yet implemented.
Decision record: [ADR-0001](../decisions/0001-warehouse-stack.md)

---

## Design goals

1. **Low V1 cost** (< $20/month for warehouse + storage).
2. **Zero-rewrite path to V2 scale** — swapping the engine should be a config change, not a refactor.
3. **Sport-agnostic schema** from the silver layer on up.
4. **Reproducibility** — every modeling run can be tied back to a versioned slice of the warehouse.
5. **Queryable history** — we keep odds snapshots and line movement, not just closing lines.

---

## High-level architecture

```
                    ┌─────────────────────┐
                    │ External sources    │
                    │ • NHL API           │
                    │ • The Odds API      │
                    │ • MoneyPuck         │
                    │ • Lineup/injury     │
                    │ • Historical odds   │
                    └──────────┬──────────┘
                               │ Python loaders (Dagster assets)
                               ▼
              ┌────────────────────────────────┐
              │ BRONZE — raw, immutable        │
              │ Parquet in object storage      │
              │ Partitioned by ingest_date     │
              │ One file per source per day    │
              └────────────────┬───────────────┘
                               │ dbt
                               ▼
              ┌────────────────────────────────┐
              │ SILVER — conformed, deduped    │
              │ Sport-agnostic entities        │
              │ DuckDB (local) / MotherDuck    │
              └────────────────┬───────────────┘
                               │ dbt
                               ▼
              ┌────────────────────────────────┐
              │ GOLD — feature marts           │
              │ Model-ready tables             │
              │ Partitioned / materialized     │
              └────────────────┬───────────────┘
                               │
                               ▼
              ┌────────────────────────────────┐
              │ Consumers                      │
              │ • Python model training        │
              │ • Daily prediction pipeline    │
              │ • Streamlit/Evidence dashboard │
              │ • (V2) Public API              │
              └────────────────────────────────┘
```

---

## Storage layer

**Object storage: Cloudflare R2.**
- S3-compatible API. Works with DuckDB, dbt-duckdb, Python, anything that speaks S3.
- Zero egress fees. This matters because DuckDB queries will pull Parquet files on demand.
- ~$0.015/GB/month. V1 storage should stay under $5/month.

**Layout.**
```
r2://nhl-bet-lake/
├── bronze/
│   ├── nhl_api/
│   │   ├── games/ingest_date=2026-04-22/games.parquet
│   │   ├── skater_stats/ingest_date=.../
│   │   ├── goalie_stats/ingest_date=.../
│   │   └── pbp/ingest_date=.../
│   ├── odds_api/
│   │   └── h2h_totals_spreads/ingest_date=.../
│   ├── moneypuck/
│   └── lineups/
└── historical/
    └── odds_archive/      # one-time purchased dataset
```

**Partitioning.** Bronze data is always partitioned by `ingest_date`. This lets us reproduce any point-in-time query and makes incremental loads trivial.

**Immutability.** Bronze files are append-only. Corrections are new ingests, not overwrites. This is the foundation of reproducibility.

---

## Compute layer

### V1: DuckDB (local) + MotherDuck (hosted)

- **Local development and backtesting**: DuckDB running against Parquet in R2 (or local cache). DuckDB can read Parquet directly over S3 — no "load step." This is stupidly fast and costs nothing locally.
- **Scheduled production pipeline**: MotherDuck (~$10/month) as a hosted DuckDB. Same SQL, same dbt project, remote execution so the pipeline doesn't need Jon's laptop.
- **dbt adapter**: `dbt-duckdb` handles both local DuckDB and MotherDuck with the same project.

### V2 path
- If scale demands it, swap MotherDuck for BigQuery or Snowflake. dbt project migrates with minor macro changes.
- Alternatively stay on MotherDuck + a read replica if subscriber load is modest (very likely for a ≤1k subscriber product).

### Why not Snowflake for V1
Credit-based pricing is unfriendly to bursty workloads. Minimum warehouse costs add up fast. No reason to pay for Snowflake scale before we have Snowflake-scale problems. See ADR-0001.

### Why not Postgres for V1
It works fine, but DuckDB is faster for analytical queries over Parquet, simpler to operate, and more consistent with the V2 warehouse paradigm. Postgres is better if we add transactional features later (user accounts, bet tracking, etc.) — and we will, but that goes in a separate OLTP database (Neon or Supabase) rather than sharing the warehouse.

---

## Sport-agnostic schema (silver layer)

Core principle: **sport and league are columns, not schemas.** Any NHL-specific term in a silver table is a bug.

### Entity model

```
sport           league          season
 │               │               │
 └───────┬───────┘               │
         ▼                       │
       team  ◄─────────── team_season ──────► player ──► player_season
         │                       │             │
         ├───────────────────────┼─────────────┘
         ▼                       ▼
       game  ◄───────────── game_lineup
         │
         ├──► game_event         (shots, goals, faceoffs, penalties, etc.)
         ├──► game_outcome       (final score + derived quantities)
         └──► market ──► odds_snapshot (time-series of odds per book)
```

### Key tables

**`dim_sport`**
- `sport_id` (pk), `sport_name` ("ice_hockey"), `period_structure`, `roster_size`, `typical_game_rate` (goals/60, runs/game, etc. — informational only)

**`dim_league`**
- `league_id` (pk), `sport_id` (fk), `league_name` ("NHL"), `country`, `tier`

**`dim_team`**
- `team_id` (pk — universal), `league_id` (fk), `external_ids` (JSON map of provider IDs), `team_name`, `arena`, `altitude_m`, `latitude`, `longitude`

**`dim_player`**
- `player_id` (pk — universal), `external_ids`, `full_name`, `position`, `shoots_catches`, `birth_date`

**`fct_game`**
- `game_id` (pk), `league_id`, `season`, `game_datetime_utc`, `home_team_id`, `away_team_id`, `venue_team_id` (for neutral-site handling), `status`

**`fct_game_outcome`**
- Final scores, regulation/OT/shootout flags, derived features for targets.

**`fct_game_lineup`**
- Per-game, per-team, per-player: starter flag, line/pairing, TOI, position. Critical for player-prop models.

**`fct_game_event`**
- Play-by-play. Shots, goals, penalties, faceoffs, hits. Long table; partition by game_datetime.

**`dim_market`**
- `market_id` (pk), `sport_id` (fk), `market_type` ("moneyline" | "total" | "spread" | "player_shots" | ...), `threshold` (for totals/spreads), `player_id` (for player props, nullable)

**`fct_odds_snapshot`**
- `snapshot_id`, `market_id`, `book`, `odds_american`, `odds_decimal`, `implied_prob`, `captured_at_utc`, `minutes_to_game`
- **One row per book per market per capture event.** We keep every snapshot we pull; we do not overwrite. This gives us historical line movement for CLV and model validation.

### Why this generalizes

- Adding MLB = new `fct_game_event` rows from a new source, new market types in `dim_market`, new sport/league rows. No schema change needed in silver.
- Adding player props for any sport = new `market_type` values and corresponding feature pipelines in gold. Silver is untouched.

---

## Gold layer

Gold tables are model-ready. They are rebuildable from silver, so they can be thrown away and regenerated whenever feature engineering changes.

**Planned gold marts (V1):**

- `mart_game_features` — one row per game per team-perspective (home/away), with pre-game features: Elo, xG rolling averages, goaltender form, rest days, travel distance, altitude, b2b flag, injury-adjusted lineup score, etc.
- `mart_player_features` — one row per player per game, pre-game: recent TOI, shots/60, on-ice xG, opponent-adjusted metrics, line partners, goaltender faced.
- `mart_market_features` — one row per market per game, with book-level odds snapshots resampled to standard intervals, open/close/movement metrics.
- `mart_picks` — model output: one row per pick, with model probability, closing implied probability, EV, Kelly size suggestion, and the feature snapshot used for audit.

All gold tables have `as_of_timestamp` and a `pipeline_run_id` foreign key for reproducibility.

---

## Orchestration

Dagster. Asset-based model maps cleanly onto bronze/silver/gold. Each dbt model is a Dagster asset via `dagster-dbt`. Python loaders are also assets. This gives us a single lineage graph across Python and SQL.

See (forthcoming) `docs/architecture/orchestration.md`.

---

## Transactional data (Phase 2)

User accounts, subscriptions, entitlements, bet-tracking, audit logs do **not** belong in the warehouse. They go in a separate OLTP database (Neon or Supabase for V1 of V2). Snapshots replicate into the warehouse for analytics.

This is the cleanest way to avoid the classic warehouse-as-application-database mess.

---

## Costs (V1 estimate)

| Component                | Estimate              |
|--------------------------|-----------------------|
| Cloudflare R2 storage    | $2–5 / month          |
| MotherDuck (hosted DuckDB) | $10 / month (standard plan) |
| Dagster Cloud (Solo)     | $0 (free tier) / month |
| The Odds API             | $0 dev / $30–60 live  |
| Historical odds (one-time) | $200–500            |
| **V1 monthly run-rate**  | **~$15–75**           |

Budget headroom for overruns or one-off data pulls.

---

## Open questions

1. Do we use MotherDuck or host DuckDB ourselves on a cheap VM? MotherDuck is simpler; self-host is cheaper if we already have a VM for Dagster.
2. Do we cache bronze files locally during backtesting to avoid R2 reads? Probably yes — caching layer to be defined.
3. Where do we store model artifacts (trained pickles, calibration params)? Options: MLflow registry, or simply versioned files in R2 under `models/`.

These will be resolved in subsequent ADRs as we hit them.
