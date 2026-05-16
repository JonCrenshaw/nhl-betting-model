-- One row per NHL team observed in bronze data.
--
-- team_abbrev and team_full_name reflect the most recent values seen in
-- bronze — this naturally handles future renames without code changes.
-- Franchise events (VGK 2017–18, SEA 2021–22, ARI→UTA 2024–25) require no
-- special mapping: the NHL API assigns each franchise a distinct team_id, so
-- ARI (id 53) and UTA (id 59) appear as separate rows with no collision.
--
-- Driving table: stg_nhl__landing (home + away appearances across all games).
-- Left join to stg_nhl__team_summary for team_full_name; a team missing from
-- team_summary will appear with a null name and should be investigated.

WITH teams_from_landing AS (

  SELECT
    home_team_id AS team_id,
    home_team_abbrev AS team_abbrev,
    fetched_at_utc
  FROM {{ ref('stg_nhl__landing') }}

  UNION ALL

  SELECT
    away_team_id AS team_id,
    away_team_abbrev AS team_abbrev,
    fetched_at_utc
  FROM {{ ref('stg_nhl__landing') }}

),

latest_abbrev AS (

  SELECT
    team_id,
    team_abbrev
  FROM teams_from_landing
  WHERE team_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY team_id ORDER BY fetched_at_utc DESC
  ) = 1

),

latest_name AS (

  SELECT
    team_id,
    team_full_name
  FROM {{ ref('stg_nhl__team_summary') }}
  WHERE team_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY team_id ORDER BY fetched_at_utc DESC
  ) = 1

)

SELECT
  a.team_id,
  a.team_abbrev,
  n.team_full_name
FROM latest_abbrev AS a
LEFT JOIN latest_name AS n ON a.team_id = n.team_id
