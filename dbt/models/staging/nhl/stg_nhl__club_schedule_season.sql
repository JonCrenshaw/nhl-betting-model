-- Staging for /v1/club-schedule-season/{team}/{season}.
--
-- One row per (season, team_abbrev). Preserves the games array as a JSON
-- blob; the intermediate layer (or fct_game) resolves individual game rows
-- via stg_nhl__landing, which is the authoritative source for game metadata.
-- This model's primary downstream consumer is int_nhl__team_spine, which
-- uses it to confirm which teams were active in which seasons.
--
-- games includes all game types (gameType 1=preseason, 2=regular, 3=playoff).
-- game_count is the total across all types; downstream filters apply game_type.
--
-- currentSeason in the response is validated against the requested season at
-- ingest time (ClubScheduleSeasonResponse.currentSeason invariant). The staging
-- model surfaces it as current_season for an additional data-quality check.

WITH source AS (

  SELECT
    *,
    JSON_EXTRACT_STRING(endpoint_params_json, '$.team') AS team_abbrev
  FROM
    READ_PARQUET(
      's3://puckbunny-lake/bronze/nhl_api/club-schedule-season/**/*.parquet',
      hive_partitioning = TRUE
    )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY
      season,
      JSON_EXTRACT_STRING(endpoint_params_json, '$.team')
    ORDER BY fetched_at_utc DESC
  ) = 1

)

SELECT
  ingest_date,
  fetched_at_utc,
  season,
  team_abbrev,
  JSON_EXTRACT(response_json, '$.games')::VARCHAR AS games_json,
  JSON_EXTRACT_STRING(response_json, '$.currentSeason') AS current_season,
  JSON_EXTRACT_STRING(response_json, '$.previousSeason') AS previous_season,
  JSON_EXTRACT_STRING(response_json, '$.nextSeason') AS next_season,
  JSON_EXTRACT_STRING(response_json, '$.clubTimezone') AS club_timezone,
  JSON_EXTRACT_STRING(response_json, '$.clubUTCOffset') AS club_utc_offset,
  JSON_ARRAY_LENGTH(
    JSON_EXTRACT(response_json, '$.games')
  ) AS game_count
FROM source
