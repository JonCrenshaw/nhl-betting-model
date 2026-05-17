-- Game spine. One row per finished NHL game.
--
-- league_id = 1 (NHL) hardcoded; sport_id propagates through dim_league.
-- venue_team_id = home_team_id by convention — landing carries venue_name
-- but no venue FK; home team is the venue host for all standard NHL games.
-- game_type: 2 = regular season, 3 = playoffs.

SELECT
  l.game_id,
  1 AS league_id,
  l.season,
  l.start_time_utc AS game_datetime_utc,
  l.home_team_id,
  l.away_team_id,
  l.home_team_id AS venue_team_id,
  l.game_type,
  l.game_state AS status
FROM {{ ref('stg_nhl__landing') }} AS l
