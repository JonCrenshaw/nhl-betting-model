-- Staging for /stats/rest/en/skater/summary.
--
-- One row per (season, player_id). The bronze envelope stores one row per
-- season fetch (the full data array); this model unnests that array into
-- per-player rows.
--
-- Deduplication strategy: deduplicate bronze rows by season first (latest
-- fetch wins), then unnest, then deduplicate again on (season, player_id)
-- to guard against any duplicates in the data array itself.
--
-- faceoff_win_pct and toi_per_game_s are null for some players (e.g. pure
-- penalty-killers with no recorded faceoffs). try_cast is used for these.
-- timeOnIcePerGame is in seconds per game (a float from the API, e.g. 1340.2).

WITH deduped_bronze AS (

  SELECT *
  FROM
    READ_PARQUET(
      's3://puckbunny-lake/bronze/nhl_api/skater-summary/**/*.parquet',
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
  JSON_EXTRACT_STRING(row_json, '$.goals')::INTEGER AS goals,
  JSON_EXTRACT_STRING(row_json, '$.assists')::INTEGER AS assists,
  JSON_EXTRACT_STRING(row_json, '$.points')::INTEGER AS points,
  JSON_EXTRACT_STRING(row_json, '$.seasonId') AS season,
  JSON_EXTRACT_STRING(row_json, '$.skaterFullName') AS skater_full_name,
  JSON_EXTRACT_STRING(row_json, '$.teamAbbrevs') AS team_abbrevs,
  JSON_EXTRACT_STRING(row_json, '$.positionCode') AS position_code,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.shots') AS INTEGER) AS shots,
  TRY_CAST(JSON_EXTRACT_STRING(row_json, '$.plusMinus') AS INTEGER) AS plus_minus,
  TRY_CAST(
    JSON_EXTRACT_STRING(row_json, '$.faceoffWinPct') AS DOUBLE
  ) AS faceoff_win_pct,
  TRY_CAST(
    JSON_EXTRACT_STRING(row_json, '$.timeOnIcePerGame') AS DOUBLE
  ) AS toi_per_game_s
FROM unnested
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY
    JSON_EXTRACT_STRING(row_json, '$.seasonId'),
    JSON_EXTRACT_STRING(row_json, '$.playerId')::INTEGER
  ORDER BY fetched_at_utc DESC
) = 1
