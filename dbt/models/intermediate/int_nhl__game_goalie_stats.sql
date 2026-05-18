-- Parse goalie rows from stg_nhl__boxscore into one row per (game_id, player_id).
--
-- toi_s converts "MM:SS" to integer seconds.
-- Scratch goalies (starter: false, toi: "00:00") are included with toi_s = 0,
-- saves = 0, and goals_against = 0 — the API always populates these fields.

WITH source AS (

  SELECT
    game_id,
    away_team_id,
    home_team_id,
    player_by_game_stats_json
  FROM {{ ref('stg_nhl__boxscore') }}

),

away_goalies AS (

  SELECT
    s.game_id,
    s.away_team_id AS team_id,
    t.player
  FROM source AS s
  CROSS JOIN UNNEST(
    JSON_EXTRACT(s.player_by_game_stats_json, '$.awayTeam.goalies')::JSON []
  ) AS t (player)

),

home_goalies AS (

  SELECT
    s.game_id,
    s.home_team_id AS team_id,
    t.player
  FROM source AS s
  CROSS JOIN UNNEST(
    JSON_EXTRACT(s.player_by_game_stats_json, '$.homeTeam.goalies')::JSON []
  ) AS t (player)

),

all_goalies AS (

  SELECT * FROM away_goalies
  UNION ALL
  SELECT * FROM home_goalies

)

-- noqa: disable=ST06 — UNNEST-derived CTE; game_id/team_id are column refs but
-- the linter cannot determine their origin through the CROSS JOIN UNNEST.
SELECT  -- noqa: ST06
  game_id,
  team_id,
  'G' AS position_type,
  JSON_EXTRACT_STRING(player, '$.playerId')::INTEGER AS player_id,
  SPLIT_PART(JSON_EXTRACT_STRING(player, '$.toi'), ':', 1)::INTEGER * 60
  + SPLIT_PART(JSON_EXTRACT_STRING(player, '$.toi'), ':', 2)::INTEGER AS toi_s,
  JSON_EXTRACT_STRING(player, '$.saves')::INTEGER AS saves,
  JSON_EXTRACT_STRING(player, '$.goalsAgainst')::INTEGER AS goals_against
FROM all_goalies
