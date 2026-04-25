# Marts

Consumer-facing gold-layer tables. The stable API between the warehouse and
everything downstream (models, dashboards, picks pipeline, Phase 2 frontend).

Naming:
- `fct_<entity>` — fact tables (events, transactions, game-level records)
- `dim_<entity>` — dimension tables (slowly-changing reference data)
- `mart_<domain>__<entity>` — domain-specific marts that combine facts
  and dimensions for a specific consumer

Examples:
- `fct_games`, `fct_odds_snapshots`, `fct_picks`
- `dim_teams`, `dim_players`, `dim_markets`
- `mart_betting__daily_picks`, `mart_clv__pick_level`

Default materialization: `table` (fast reads; rebuilt by the daily pipeline).

Sport-agnostic rule: every fact and dimension carries `sport_id` and
`league_id` as columns. No NHL-specific assumptions in gold. A clean port
to MLB should be "add new staging/intermediate models, reuse the mart
schemas as-is."
