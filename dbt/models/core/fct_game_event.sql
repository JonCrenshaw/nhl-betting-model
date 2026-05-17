-- Sport-agnostic game event table. One row per play-by-play event.
--
-- event_type maps NHL typeDescKey to a generic vocabulary using a
-- hyphen-to-underscore replacement, with one explicit alias:
-- shot-on-goal -> shot. Unknown future event types fall through to the
-- replace pattern and land with their typeDescKey slug intact.
--
-- Structural events (period_start, period_end, game_end) have null
-- team_id, coordinates, and player IDs — they carry no details block
-- (ADR-0003 D3). All other null player/coord fields are normal for events
-- where those participants are not applicable.
--
-- situationCode (power-play state) is a top-level play field not captured
-- here; add it to this model when M5 feature engineering needs it.

SELECT
  game_id,
  period,
  period_time_elapsed_s,
  x_coord,
  y_coord,
  event_team_id AS team_id,
  primary_player_id,
  secondary_player_id,
  details_json,
  CONCAT(game_id::VARCHAR, '_', event_sequence::VARCHAR) AS event_id,
  CASE type_desc_key
    WHEN 'shot-on-goal' THEN 'shot'
    ELSE REPLACE(type_desc_key, '-', '_')
  END AS event_type
FROM {{ ref('int_nhl__game_events') }}
