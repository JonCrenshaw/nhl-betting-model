# `team_season/` cassette fixtures

Recorded against the live `api-web.nhle.com` API on 2026-05-04 by the
PR-F2 inline probe. Fixtures are checked in verbatim — preserving the
exact byte sequence so the loader's `response_sha256` invariant stays
deterministic across test runs.

| File | Endpoint | Status | Size | Source |
|------|----------|--------|------|--------|
| `roster_TOR_20242025.json` | `/v1/roster/TOR/20242025` | 200 | 17,935 B | live API |
| `club_schedule_season_TOR_20242025.json` | `/v1/club-schedule-season/TOR/20242025` | 200 | 202,274 B | live API |
| `roster_UTA_20232024_404.html` | `/v1/roster/UTA/20232024` | 404 | 367 B | live API (reference only) |

The 404 HTML artifact is **not used by any test** — `test_nhl_team_season.py`
stubs its own minimal HTML 404 body via `MockTransport` rather than
coupling to NHL's particular Jetty error template, so the fixture
exists purely as documentation of what the API returns on
`(team, season)` pairs the franchise didn't exist for. See
[`docs/ideas/prf2-spike-notes.md`](../../../../docs/ideas/prf2-spike-notes.md)
§3 for the 404 contract details.

## Re-recording

If the NHL changes either endpoint's payload shape and we need fresh
fixtures, the probe script lives only in `prf2-spike-notes.md` git
history (it was inline). Adapt and re-run; commit the new bodies
verbatim. Same User-Agent (`PuckBunny/0.1 (contact: …)`) for
politeness and identifiability.
