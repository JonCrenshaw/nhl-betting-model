# core/

Silver layer — conformed, sport-agnostic `dim_*` and `fct_*` tables materialized
as tables in the `core` schema in DuckDB/MotherDuck.

This is the layer M4 (odds), M5 (features), and all downstream milestones
consume. Nothing above this layer should touch bronze Parquet directly.

Sport-agnostic means: no NHL-specific field names, no hardcoded period counts
or roster sizes. `sport_id` and `league_id` are first-class columns on every
table. New sports plug in here by adding staging + intermediate models; the
core schema stays unchanged.

## Tables in this layer (M3)

| Model | Type | Description |
|---|---|---|
| `dim_sport` | seed | Sports registry (ice_hockey, ...) |
| `dim_league` | seed | Leagues per sport (NHL, ...) |
| `dim_team` | dim | One row per team per league |
| `dim_player` | dim | One row per player |
| `fct_game` | fct | Game spine — datetime, teams, status |
| `fct_game_outcome` | fct | Final scores, regulation/OT/SO flag |
| `fct_game_event` | fct | Sport-agnostic play-by-play events |
| `fct_game_lineup` | fct | Per-player per-game stats and TOI |

`dim_market` and `fct_odds_snapshot` are deferred to M4 (no odds data in
bronze yet). See M3 decision D1.
