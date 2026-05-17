-- Game outcome. One row per finished NHL game.
--
-- winning_team_id is derived from score comparison. Ties are not possible
-- in finished NHL games (landing is filtered to FINAL/OFF game_state).
-- period_end passes through final_period_type directly: REG, OT, or SO.

SELECT
  l.game_id,
  l.home_score AS home_goals,
  l.away_score AS away_goals,
  l.final_period_type AS period_end,
  CASE
    WHEN l.home_score > l.away_score THEN l.home_team_id
    ELSE l.away_team_id
  END AS winning_team_id,
  l.home_score > l.away_score AS home_win
FROM {{ ref('stg_nhl__landing') }} AS l
