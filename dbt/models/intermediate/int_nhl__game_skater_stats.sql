-- Parse skater rows from stg_nhl__boxscore into one row per (game_id, player_id).
--
-- Covers forwards (position_type F) and defensemen (position_type D) for both
-- teams. The boxscore API uses "defense" (not "defensemen") as the JSON key for
-- the defensemen array — see stg_nhl__boxscore comment.
--
-- toi_s converts "MM:SS" to integer seconds (same pattern as int_nhl__game_events).
-- sog is exposed as shots to match the sport-agnostic fct_game_lineup column name.

WITH source AS (

  SELECT
    game_id,
    away_team_id,
    home_team_id,
    player_by_game_stats_json
  FROM {{ ref('stg_nhl__boxscore') }}

),

away_forwards AS (

  SELECT
    s.game_id,
    s.away_team_id AS team_id,
    'F' AS position_type,
    t.player
  FROM source AS s
  CROSS JOIN UNNEST(
    JSON_EXTRACT(s.player_by_game_stats_json, '$.awayTeam.forwards')::JSON []
  ) AS t (player)

),

away_defense AS (

  SELECT
    s.game_id,
    s.away_team_id AS team_id,
    'D' AS position_type,
    t.player
  FROM source AS s
  CROSS JOIN UNNEST(
    JSON_EXTRACT(s.player_by_game_stats_json, '$.awayTeam.defense')::JSON []
  ) AS t (player)

),

home_forwards AS (

  SELECT
    s.game_id,
    s.home_team_id AS team_id,
    'F' AS position_type,
    t.player
  FROM source AS s
  CROSS JOIN UNNEST(
    JSON_EXTRACT(s.player_by_game_stats_json, '$.homeTeam.forwards')::JSON []
  ) AS t (player)

),

home_defense AS (

  SELECT
    s.game_id,
    s.home_team_id AS team_id,
    'D' AS position_type,
    t.player
  FROM source AS s
  CROSS JOIN UNNEST(
    JSON_EXTRACT(s.player_by_game_stats_json, '$.homeTeam.defense')::JSON []
  ) AS t (player)

),

all_skaters AS (

  SELECT * FROM away_forwards
  UNION ALL
  SELECT * FROM away_defense
  UNION ALL
  SELECT * FROM home_forwards
  UNION ALL
  SELECT * FROM home_defense

)

-- noqa: disable=ST06 — UNNEST-derived CTE; game_id/team_id are column refs but
-- the linter cannot determine their origin through the CROSS JOIN UNNEST.
SELECT  -- noqa: ST06
  game_id,
  team_id,
  position_type,
  JSON_EXTRACT_STRING(player, '$.playerId')::INTEGER AS player_id,
  SPLIT_PART(JSON_EXTRACT_STRING(player, '$.toi'), ':', 1)::INTEGER * 60
  + SPLIT_PART(JSON_EXTRACT_STRING(player, '$.toi'), ':', 2)::INTEGER AS toi_s,
  JSON_EXTRACT_STRING(player, '$.goals')::INTEGER AS goals,
  JSON_EXTRACT_STRING(player, '$.assists')::INTEGER AS assists,
  JSON_EXTRACT_STRING(player, '$.sog')::INTEGER AS shots
FROM all_skaters
