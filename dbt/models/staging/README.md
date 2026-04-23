# Staging models

Thin cleaning layer over raw (bronze) data. One staging model per source entity.

Naming: `stg_<source>__<entity>`
Example: `stg_nhl_api__games`, `stg_odds_api__moneyline`

Materialization: `view` (cheap, always fresh).

What belongs here:
- Type coercion (strings → timestamps, numerics → proper types)
- Column renames to project conventions (`id` → `<entity>_id`)
- Light filtering (drop known-bad rows, test data)
- Deduplication on the source primary key

What does **not** belong here:
- Joins across sources (that's intermediate)
- Business logic or derived metrics (that's marts)
- Sport-specific assumptions baked into generic fields (keep `sport` and
  `league` as dimensions, not schema)

Each model gets a `schema.yml` entry with column descriptions and at least
`unique` + `not_null` tests on the primary key.

Subdirectories by source are encouraged as this layer grows:
`staging/nhl_api/`, `staging/odds_api/`, etc.
