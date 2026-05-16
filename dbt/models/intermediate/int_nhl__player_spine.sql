-- One row per NHL player observed across roster, skater summary, and goalie
-- summary. Deduplicates on player_id; demographics come from the most recent
-- roster row (richest source). Skater/goalie summary names fill in players
-- who appeared in season stats but were never on a bronze roster pull.
--
-- Position derivation priority:
--   1. position_group from roster (authoritative: 'F', 'D', 'G')
--   2. Inferred from skater_summary.position_code (C/L/R → 'F', D → 'D')
--   3. Inferred from goalie_summary presence → 'G'
--
-- fct_game_lineup (PR-F) will add players who appear only in boxscore JSON
-- and have no roster or summary row (rare; edge cases like emergency callups).

WITH roster_latest AS (

  SELECT
    player_id,
    first_name,
    last_name,
    position_group,
    position_code,
    shoots_catches,
    height_in,
    weight_lb,
    birth_date,
    birth_country,
    fetched_at_utc
  FROM {{ ref('stg_nhl__roster') }}
  WHERE player_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY player_id ORDER BY fetched_at_utc DESC
  ) = 1

),

skater_latest AS (

  SELECT
    player_id,
    skater_full_name AS full_name,
    position_code
  FROM {{ ref('stg_nhl__skater_summary') }}
  WHERE player_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY player_id ORDER BY fetched_at_utc DESC
  ) = 1

),

goalie_latest AS (

  SELECT
    player_id,
    goalie_full_name AS full_name
  FROM {{ ref('stg_nhl__goalie_summary') }}
  WHERE player_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY player_id ORDER BY fetched_at_utc DESC
  ) = 1

),

all_players AS (

  SELECT player_id FROM roster_latest
  UNION
  SELECT player_id FROM skater_latest
  UNION
  SELECT player_id FROM goalie_latest

)

SELECT
  p.player_id,

  -- Full name: prefer roster concatenation, fall back to summary names
  r.first_name,

  r.last_name,
  r.shoots_catches,

  -- Position group: roster is authoritative; infer from summaries otherwise
  r.height_in,

  r.weight_lb,

  r.birth_date,
  r.birth_country,
  COALESCE(
    CASE
      WHEN r.first_name IS NOT NULL AND r.last_name IS NOT NULL
        THEN r.first_name || ' ' || r.last_name
    END,
    s.full_name,
    g.full_name
  ) AS full_name,
  COALESCE(
    r.position_group,
    CASE
      WHEN s.position_code IN ('C', 'L', 'R') THEN 'F'
      WHEN s.position_code = 'D' THEN 'D'
      WHEN g.player_id IS NOT NULL THEN 'G'
    END
  ) AS position_group,
  COALESCE(r.position_code, s.position_code) AS position_code

FROM all_players AS p
LEFT JOIN roster_latest AS r ON p.player_id = r.player_id
LEFT JOIN skater_latest AS s ON p.player_id = s.player_id
LEFT JOIN goalie_latest AS g ON p.player_id = g.player_id
