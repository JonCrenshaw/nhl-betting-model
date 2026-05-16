-- Silver player dimension. One row per NHL player.
--
-- player_id is the NHL API's stable integer identifier. It is unique within
-- the NHL and serves as the PK. No league_id FK here: a player can appear
-- in multiple leagues (e.g. AHL call-up → NHL); the association belongs in
-- fct_game_lineup, not in the player dimension.
--
-- Demographics (height, weight, birth_date, birth_country) come from the
-- most recent roster pull and may be null for players who appear only in
-- season summary data. full_name is always populated.
--
-- external_ids carries the raw NHL API player identifier for cross-source
-- joins (e.g. joining to a third-party stats provider's player table).

SELECT
  p.player_id,
  p.full_name,
  p.first_name,
  p.last_name,
  p.position_group,
  p.position_code,
  p.shoots_catches,
  p.height_in,
  p.weight_lb,
  p.birth_date,
  p.birth_country,
  JSON_OBJECT('nhl_api_player_id', p.player_id) AS external_ids
FROM {{ ref('int_nhl__player_spine') }} AS p
