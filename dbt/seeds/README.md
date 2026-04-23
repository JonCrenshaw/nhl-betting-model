# Seeds

Small CSV files checked into the repo and loaded via `dbt seed`. Good for
reference data that rarely changes and isn't worth a full ingestion pipeline:
team codes, market-type registry, sport/league dimension seeds.

Do **not** use seeds for anything that's updated more than monthly or is
larger than a few thousand rows. Point those at proper ingestion.
