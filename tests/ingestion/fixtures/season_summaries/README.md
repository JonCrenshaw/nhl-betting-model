# Season-summary NHL API fixtures

Hand-crafted minimal payloads modeled on the
`api.nhle.com/stats/rest/en/{skater,goalie,team}/summary` surface
shape verified by the PR-F0 spike (see
`docs/ideas/prf-stats-rest-spike-notes.md`). Used by
`tests/ingestion/test_nhl_season_summaries.py` to exercise schema
validation and the `season_summaries.py` loader without hitting the
network.

| File | Endpoint | Rows |
|------|----------|------|
| `skater_summary_20242025.json` | `/stats/rest/en/skater/summary?cayenneExp=seasonId=20242025&limit=-1` | 2 |
| `goalie_summary_20242025.json` | `/stats/rest/en/goalie/summary?cayenneExp=seasonId=20242025&limit=-1` | 2 |
| `team_summary_20242025.json` | `/stats/rest/en/team/summary?cayenneExp=seasonId=20242025&limit=-1` | 2 |

These are **hand-crafted** — not recorded responses — so the
`len(data) == total` envelope invariant is hand-checkable and the
fixture JSON stays small enough to read at a glance. Field shapes
mirror what the PR-F0 spike observed (per-row `seasonId`,
`playerId`/`teamId`, `gamesPlayed`, common scoring/goaltending stats,
`teamAbbrevs` as comma-joined string for traded players, `ties: null`
as a vestigial pre-shootout-era field). Player IDs and team IDs are
realistic but the per-row aggregate values are illustrative —
treating them as ground truth would be a mistake.

Refresh policy: only re-craft if a parser change requires shape we
don't currently exercise, or if NHL changes the envelope contract.
The fixtures' value is that they're a known, hand-checkable shape.
