-- Staging for /v1/gamecenter/{gameId}/boxscore.
--
-- One row per game. Shares top-level metadata with stg_nhl__landing but
-- adds game outcome (last_period_type, ot_periods) and preserves
-- playerByGameStats as a JSON blob for the intermediate layer to unnest
-- into int_nhl__game_skater_stats and int_nhl__game_goalie_stats.
--
-- Note: the boxscore fixture uses "defense" (not "defensemen") as the key
-- for the defensemen group inside playerByGameStats. The intermediate model
-- handles that naming.

WITH source AS (

  SELECT *
  FROM
    READ_PARQUET(
      's3://puckbunny-lake/bronze/nhl_api/boxscore/**/*.parquet',
      hive_partitioning = TRUE
    )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY JSON_EXTRACT_STRING(response_json, '$.id')::BIGINT
    ORDER BY fetched_at_utc DESC
  ) = 1

)

SELECT
  ingest_date,
  fetched_at_utc,
  JSON_EXTRACT_STRING(response_json, '$.id')::BIGINT AS game_id,
  JSON_EXTRACT_STRING(response_json, '$.gameType')::INTEGER AS game_type,
  STRPTIME(
    JSON_EXTRACT_STRING(response_json, '$.gameDate'),
    '%Y-%m-%d'
  )::DATE AS game_date,
  JSON_EXTRACT_STRING(response_json, '$.startTimeUTC')::TIMESTAMPTZ
    AS start_time_utc,
  JSON_EXTRACT_STRING(response_json, '$.awayTeam.id')::INTEGER AS away_team_id,
  JSON_EXTRACT_STRING(response_json, '$.homeTeam.id')::INTEGER AS home_team_id,
  JSON_EXTRACT(response_json, '$.playerByGameStats')::VARCHAR
    AS player_by_game_stats_json,
  JSON_EXTRACT_STRING(response_json, '$.season') AS season,
  JSON_EXTRACT_STRING(response_json, '$.gameState') AS game_state,
  JSON_EXTRACT_STRING(response_json, '$.awayTeam.abbrev') AS away_team_abbrev,
  JSON_EXTRACT_STRING(response_json, '$.homeTeam.abbrev') AS home_team_abbrev,
  JSON_EXTRACT_STRING(
    response_json, '$.gameOutcome.lastPeriodType'
  ) AS last_period_type,
  TRY_CAST(
    JSON_EXTRACT_STRING(response_json, '$.gameOutcome.otPeriods')
    AS INTEGER
  ) AS ot_periods
FROM source
