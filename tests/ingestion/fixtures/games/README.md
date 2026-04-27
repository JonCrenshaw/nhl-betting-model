# Game-level NHL API fixtures

Verbatim JSON payloads recorded during the PR-A spike against the live
`api-web.nhle.com` surface on 2026-04-25. Used by
`tests/ingestion/test_nhl_*.py` to exercise schema validation and the
`games.py` loader without hitting the network.

| File | Endpoint | Game |
|------|----------|------|
| `landing_2025030123.json` | `/v1/gamecenter/2025030123/landing` | TBL @ MTL, 2026-04-24, playoffs (gameType=3) |
| `boxscore_2025030123.json` | `/v1/gamecenter/2025030123/boxscore` | (same game) |
| `play_by_play_2025030123.json` | `/v1/gamecenter/2025030123/play-by-play` | (same game) — 319 plays, 40 rosterSpots; key scan in `docs/ideas/prd-pbp-keys.md` |

Refresh policy: only re-record if a parser change requires shape we
don't currently exercise, or if NHL changes the schema and our pydantic
models need to follow. Don't re-record routinely — the value of these
fixtures is that they're a known, stable shape.
