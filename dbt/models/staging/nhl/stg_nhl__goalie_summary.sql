-- Staging for /stats/rest/en/goalie/summary.
--
-- One row per (season, player_id). Mirrors the structure of
-- stg_nhl__skater_summary: deduplicate bronze by season, unnest the data
-- array, deduplicate again on (season, player_id).
--
-- savePct and goalsAgainstAverage are null for goalies with 0 games played
-- (e.g. emergency backups). ties is null for all modern seasons.

WITH deduped_bronze AS (

  SELECT *
  FROM
    READ_PARQUET(
      's3://puckbunny-lake/bronze/nhl_api/goalie-summary/**/*.parquet',
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
  JSON_EXTRACT_STRING(row_json, '$.playerId')::INTEGER AS player_id,
  JSON_EXTRACT_STRING(row_json, '$.gamesPlayed')::INTEGER AS games_played,
  JSON_EXTRACT_STRING(row_json, '$.seasonId') AS season,
  JSON_EXTRACT_STRING(row_json, '$.goalieFullName') AS goalie_full_name,
  JSON_EXTRACT_STRING(row_json, '$.teamAbbrevs') AS team_abbrevs,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.wins') AS INTEGER) AS wins,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.losses') AS INTEGER) AS losses,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.otLosses') AS INTEGER) AS ot_losses,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.savePct') AS DOUBLE) AS save_pct,
  TRY_CAST(
    JSON_EXTRACT_STRING(row_json, '$.goalsAgainstAverage') AS DOUBLE
  ) AS goals_against_avg,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.shutouts') AS INTEGER) AS shutouts
FROM unnested
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY
    JSON_EXTRACT_STRING(row_json, '$.seasonId'),
    JSON_EXTRACT_STRING(row_json, '$.playerId')::INTEGER
  ORDER BY fetched_at_utc DESC
) = 1
