-- Staging for /stats/rest/en/team/summary.
--
-- One row per (season, team_id). The season-summary response includes
-- both regular-season and playoff games in gamesPlayed — downstream
-- models that need only regular-season data must filter by joining to
-- fct_game with game_type = 2.
--
-- pointPct, regulationAndOtWins, and goalsForPerGame are null for teams
-- whose season data is incomplete (rare; use try_cast defensively).

WITH deduped_bronze AS (

  SELECT *
  FROM
    READ_PARQUET(
      's3://puckbunny-lake/bronze/nhl_api/team-summary/**/*.parquet',
      hive_partitioning = TRUE
    )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY season
    ORDER BY fetched_at_utc DESC
  ) = 1

),

unnested AS (

  SELECT
    fetched_at_utc,
    ingest_date,
    UNNEST(
      JSON_EXTRACT(response_json, '$.data')::JSON []
    ) AS row_json
  FROM deduped_bronze

)

SELECT
  ingest_date,
  fetched_at_utc,
  JSON_EXTRACT_STRING(row_json, '$.teamId')::INTEGER AS team_id,
  JSON_EXTRACT_STRING(row_json, '$.gamesPlayed')::INTEGER AS games_played,
  JSON_EXTRACT_STRING(row_json, '$.seasonId') AS season,
  JSON_EXTRACT_STRING(row_json, '$.teamFullName') AS team_full_name,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.wins') AS INTEGER) AS wins,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.losses') AS INTEGER) AS losses,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.otLosses') AS INTEGER) AS ot_losses,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.points') AS INTEGER) AS points,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.pointPct') AS DOUBLE) AS point_pct,
  TRY_CAST(
    JSON_EXTRACT_STRING(row_json, '$.regulationAndOtWins') AS INTEGER
  ) AS regulation_and_ot_wins,
  TRY_CAST(
    JSON_EXTRACT_STRING(row_json, '$.goalsForPerGame') AS DOUBLE
  ) AS goals_for_per_game,
  TRY_CAST(
    JSON_EXTRACT_STRING(row_json, '$.goalsAgainstPerGame') AS DOUBLE
  ) AS goals_against_per_game
FROM unnested
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY
    JSON_EXTRACT_STRING(row_json, '$.seasonId'),
    JSON_EXTRACT_STRING(row_json, '$.teamId')::INTEGER
  ORDER BY fetched_at_utc DESC
) = 1
