# Snapshots

dbt snapshots capture slowly-changing-dimension history. Expected uses in
PuckBunny:

- Team/player reference data that changes over time (trades, retirements,
  name changes)
- Market registry changes (a book adding a new prop market, retiring an old
  market type)

Odds history does **not** belong here — odds are a high-volume time series
and go into `fct_odds_snapshots` populated by the odds-ingestion pipeline,
not a dbt snapshot.
