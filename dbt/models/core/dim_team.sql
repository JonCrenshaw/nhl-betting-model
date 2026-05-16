-- Silver team dimension. One row per NHL team.
--
-- team_id is the NHL API's stable integer identifier. It is unique within the
-- NHL and serves as the PK. When a second sport is onboarded, an ADR will
-- address cross-sport key uniqueness (e.g. composite or hash surrogate).
--
-- league_id = 1 (NHL) is hardcoded; sport_id propagates through dim_league.
-- Arena, city, and geography columns are nullable — not present in bronze;
-- populate from a future enrichment source (e.g. a teams seed CSV).
-- external_ids carries the raw NHL API team identifier for cross-source joins.

SELECT
  t.team_id,
  1 AS league_id,
  t.team_abbrev,
  t.team_full_name,
  NULL::VARCHAR AS arena_name,
  NULL::VARCHAR AS city,
  NULL::VARCHAR AS state_province,
  NULL::VARCHAR AS country_code,
  JSON_OBJECT('nhl_api_team_id', t.team_id) AS external_ids
FROM {{ ref('int_nhl__team_spine') }} AS t
