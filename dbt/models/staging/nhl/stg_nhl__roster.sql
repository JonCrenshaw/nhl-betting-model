-- Staging for /v1/roster/{team}/{season}.
--
-- One row per (season, team_abbrev, player_id). The roster response has no
-- top-level season or team fields; both are sourced from the bronze envelope
-- (season column and endpoint_params_json).
--
-- The three position groups (forwards, defensemen, goalies) are unioned
-- into a single table with position_group ('F', 'D', 'G') as a discriminator.
-- position_code provides the finer-grained position (C, L, R, D, G).
--
-- sweater_number is null for unsigned/AHL callup players who appear in the
-- roster response without an active number. birthDate is null for a small
-- fraction of international players. try_cast is used for both.
--
-- Franchise events (VGK 2017-18, SEA 2021-22, ARI→UTA 2024-25) are handled
-- upstream in int_nhl__team_spine; staging passes team_abbrev through as-is.

WITH deduped_bronze AS (

  SELECT
    *,
    JSON_EXTRACT_STRING(endpoint_params_json, '$.team') AS team_abbrev
  FROM
    READ_PARQUET(
      's3://puckbunny-lake/bronze/nhl_api/roster/**/*.parquet',
      hive_partitioning = TRUE
    )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY
      season,
      JSON_EXTRACT_STRING(endpoint_params_json, '$.team')
    ORDER BY fetched_at_utc DESC
  ) = 1

),

forwards AS (

  SELECT
    season,
    team_abbrev,
    fetched_at_utc,
    ingest_date,
    'F' AS position_group,
    UNNEST(
      JSON_EXTRACT(response_json, '$.forwards')::JSON []
    ) AS player_json
  FROM deduped_bronze

),

defensemen AS (

  SELECT
    season,
    team_abbrev,
    fetched_at_utc,
    ingest_date,
    'D' AS position_group,
    UNNEST(
      JSON_EXTRACT(response_json, '$.defensemen')::JSON []
    ) AS player_json
  FROM deduped_bronze

),

goalies AS (

  SELECT
    season,
    team_abbrev,
    fetched_at_utc,
    ingest_date,
    'G' AS position_group,
    UNNEST(
      JSON_EXTRACT(response_json, '$.goalies')::JSON []
    ) AS player_json
  FROM deduped_bronze

),

combined AS (

  SELECT * FROM forwards
  UNION ALL
  SELECT * FROM defensemen
  UNION ALL
  SELECT * FROM goalies

)

SELECT
  ingest_date,
  fetched_at_utc,
  season,
  team_abbrev,
  position_group,
  JSON_EXTRACT_STRING(player_json, '$.id')::INTEGER AS player_id,
  JSON_EXTRACT_STRING(player_json, '$.positionCode') AS position_code,
  JSON_EXTRACT_STRING(player_json, '$.firstName.default') AS first_name,
  JSON_EXTRACT_STRING(player_json, '$.lastName.default') AS last_name,
  TRY_CAST(
    JSON_EXTRACT_STRING(player_json, '$.sweaterNumber') AS INTEGER
  ) AS sweater_number,
  JSON_EXTRACT_STRING(player_json, '$.shootsCatches') AS shoots_catches,
  TRY_CAST(
    JSON_EXTRACT_STRING(player_json, '$.heightInInches') AS INTEGER
  ) AS height_in,
  TRY_CAST(
    JSON_EXTRACT_STRING(player_json, '$.weightInPounds') AS INTEGER
  ) AS weight_lb,
  TRY_CAST(
    JSON_EXTRACT_STRING(player_json, '$.birthDate') AS DATE
  ) AS birth_date,
  JSON_EXTRACT_STRING(player_json, '$.birthCountry') AS birth_country
FROM combined
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY
    season,
    team_abbrev,
    JSON_EXTRACT_STRING(player_json, '$.id')::INTEGER
  ORDER BY fetched_at_utc DESC
) = 1
