-- Staging for /v1/gamecenter/{gameId}/landing.
--
-- One row per game. Deduplicates to the latest fetch per game_id.
-- Carries game metadata unique to landing (venue_timezone, ot/shootout flags,
-- final period type). Score is available here; use stg_nhl__boxscore for
-- player-level stats and stg_nhl__play_by_play for event detail.
--
-- D6 convention (docs/milestones/m3-silver-layer.md): read_parquet with
-- hive_partitioning, deduplicate via QUALIFY, extract typed columns from
-- response_json, leave response_json behind.

WITH source AS (

  SELECT *
  FROM
    READ_PARQUET(
      's3://puckbunny-lake/bronze/nhl_api/landing/**/*.parquet',
      hive_partitioning = TRUE
    )
  WHERE JSON_EXTRACT_STRING(response_json, '$.gameType')::INTEGER IN (2, 3)
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
  JSON_EXTRACT_STRING(response_json, '$.awayTeam.score')::INTEGER AS away_score,
  JSON_EXTRACT_STRING(response_json, '$.homeTeam.id')::INTEGER AS home_team_id,
  JSON_EXTRACT_STRING(response_json, '$.homeTeam.score')::INTEGER AS home_score,
  JSON_EXTRACT_STRING(response_json, '$.regPeriods')::INTEGER AS reg_periods,
  JSON_EXTRACT_STRING(response_json, '$.otInUse')::BOOLEAN AS ot_in_use,
  JSON_EXTRACT_STRING(response_json, '$.shootoutInUse')::BOOLEAN AS shootout_in_use,
  JSON_EXTRACT_STRING(response_json, '$.season') AS season,
  JSON_EXTRACT_STRING(response_json, '$.gameState') AS game_state,
  JSON_EXTRACT_STRING(response_json, '$.awayTeam.abbrev') AS away_team_abbrev,
  JSON_EXTRACT_STRING(response_json, '$.homeTeam.abbrev') AS home_team_abbrev,
  JSON_EXTRACT_STRING(response_json, '$.venue.default') AS venue_name,
  JSON_EXTRACT_STRING(response_json, '$.venueTimezone') AS venue_timezone,
  JSON_EXTRACT_STRING(
    response_json, '$.periodDescriptor.periodType'
  ) AS final_period_type
FROM source
