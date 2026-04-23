# Intermediate models

Transformations that aren't yet marts but combine or reshape staging models.

Naming: `int_<entity>__<purpose>`
Example: `int_games__with_rest_days`, `int_players__roster_as_of_game`

Default materialization: `ephemeral` (inlined as CTEs; no warehouse cost).
Override to `view` or `table` if a model is reused enough to warrant
materialization.

What belongs here:
- Joins across staging models
- As-of-date joins (players, lineups, injuries aligned to a game timestamp —
  crucial for avoiding feature leakage)
- Intermediate aggregations feeding multiple marts

What does **not** belong here:
- Direct reads from raw sources (stage them first)
- Final consumer-facing artifacts (that's marts)

Intermediate models are where most feature engineering actually happens.
Per CLAUDE.md, prefer warehouse-native feature engineering over Python when
the transformation can be expressed in SQL.
