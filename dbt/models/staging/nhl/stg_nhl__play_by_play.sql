-- Staging for /v1/gamecenter/{gameId}/play-by-play.
--
-- One row per game. Preserves the plays array and rosterSpots array as JSON
-- blobs for the intermediate layer. int_nhl__game_events unnests plays into
-- one row per event. play_count is a data-quality signal.
--
-- play_count is 0 for no events, suspicious for any finished game.
-- The three structural event types (period-start, period-end, game-end) have
-- no details block; downstream consumers must handle null coordinates and
-- player IDs for those events (ADR-0003 D3).

WITH source AS (

  SELECT *
  FROM
    READ_PARQUET(
      's3://puckbunny-lake/bronze/nhl_api/play-by-play/**/*.parquet',
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
  JSON_EXTRACT(response_json, '$.plays')::VARCHAR AS plays_json,
  JSON_EXTRACT(response_json, '$.rosterSpots')::VARCHAR AS roster_spots_json,
  JSON_EXTRACT_STRING(response_json, '$.season') AS season,
  JSON_EXTRACT_STRING(response_json, '$.gameState') AS game_state,
  JSON_EXTRACT_STRING(response_json, '$.awayTeam.abbrev') AS away_team_abbrev,
  JSON_EXTRACT_STRING(response_json, '$.homeTeam.abbrev') AS home_team_abbrev,
  JSON_ARRAY_LENGTH(
    JSON_EXTRACT(response_json, '$.plays')
  ) AS play_count
FROM source
