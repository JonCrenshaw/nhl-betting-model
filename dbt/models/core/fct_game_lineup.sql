-- Sport-agnostic per-player game participation table.
--
-- Union of skaters (position_type F/D) and goalies (position_type G). Columns
-- that apply only to one role are null for the other: saves and goals_against
-- are null for skaters; goals, assists, and shots are null for goalies.
--
-- lineup_id is a stable surrogate PK composed of game_id and player_id,
-- following the same pattern as event_id in fct_game_event.
--
-- Line and pairing assignments are not available from M2 bronze; add them
-- when a future data source provides them.

SELECT
  CONCAT(game_id::VARCHAR, '_', player_id::VARCHAR) AS lineup_id,
  game_id,
  team_id,
  player_id,
  position_type,
  toi_s,
  goals,
  assists,
  shots,
  NULL::INTEGER AS saves,
  NULL::INTEGER AS goals_against
FROM {{ ref('int_nhl__game_skater_stats') }}

UNION ALL

SELECT
  CONCAT(game_id::VARCHAR, '_', player_id::VARCHAR) AS lineup_id,
  game_id,
  team_id,
  player_id,
  position_type,
  toi_s,
  NULL::INTEGER AS goals,
  NULL::INTEGER AS assists,
  NULL::INTEGER AS shots,
  saves,
  goals_against
FROM {{ ref('int_nhl__game_goalie_stats') }}
