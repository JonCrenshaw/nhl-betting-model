-- Unnest the plays array from stg_nhl__play_by_play into one row per event.
--
-- FROM-clause CROSS JOIN UNNEST rather than UNNEST-in-SELECT.
-- Both are equivalent in DuckDB; JSON [] cast follows D6 convention
-- (docs/milestones/m3-silver-layer.md).
--
-- Three structural events (period-start, period-end, game-end) carry no
-- details block (ADR-0003 D3) — event_team_id, coordinates, and player IDs
-- are null for those rows by design.
--
-- primary_player_id resolution order: scorer > shooter > hitter > blocker >
-- faceoff winner > penalty committer > generic player.
-- secondary_player_id resolution order: first assist > goalie in net >
-- hittee > faceoff loser > penalty drawer.

WITH plays_unnested AS (

  SELECT
    p.game_id,
    t.play
  FROM {{ ref('stg_nhl__play_by_play') }} AS p
  CROSS JOIN UNNEST(p.plays_json::JSON []) AS t (play)

)

-- noqa: disable=ST06 — UNNEST-derived CTE; game_id is a column ref but
-- the linter cannot determine its origin through the CROSS JOIN UNNEST.
SELECT  -- noqa: ST06
  game_id,
  JSON_EXTRACT_STRING(play, '$.typeDescKey') AS type_desc_key,
  JSON_EXTRACT_STRING(play, '$.periodDescriptor.periodType') AS period_type,
  JSON_EXTRACT_STRING(play, '$.timeInPeriod') AS time_in_period_raw,
  JSON_EXTRACT_STRING(play, '$.eventId')::INTEGER AS event_sequence,
  JSON_EXTRACT_STRING(play, '$.periodDescriptor.number')::INTEGER AS period,
  JSON_EXTRACT_STRING(play, '$.details.eventOwnerTeamId')::INTEGER AS event_team_id,
  JSON_EXTRACT_STRING(play, '$.details.xCoord')::INTEGER AS x_coord,
  JSON_EXTRACT_STRING(play, '$.details.yCoord')::INTEGER AS y_coord,
  JSON_EXTRACT(play, '$.details')::VARCHAR AS details_json,
  SPLIT_PART(
    JSON_EXTRACT_STRING(play, '$.timeInPeriod'), ':', 1
  )::INTEGER * 60
  + SPLIT_PART(
    JSON_EXTRACT_STRING(play, '$.timeInPeriod'), ':', 2
  )::INTEGER AS period_time_elapsed_s,
  COALESCE(
    JSON_EXTRACT_STRING(play, '$.details.scoringPlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.shootingPlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.hittingPlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.blockingPlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.winningPlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.committedByPlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.playerId')::INTEGER
  ) AS primary_player_id,
  COALESCE(
    JSON_EXTRACT_STRING(play, '$.details.assist1PlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.goalieInNetId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.hitteePlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.losingPlayerId')::INTEGER,
    JSON_EXTRACT_STRING(play, '$.details.drawnByPlayerId')::INTEGER
  ) AS secondary_player_id
FROM plays_unnested
