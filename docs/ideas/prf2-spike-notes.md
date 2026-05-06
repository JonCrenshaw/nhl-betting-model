# PR-F2 spike — `/v1/roster` + `/v1/club-schedule-season` payload probe

**2026-05-04.** Inline first-commit probe rather than a separate
PR-F0-style spike PR (per CLAUDE.md / PR-F2 plan: PR-A had already
validated the host, so the unknowns were per-endpoint shape rather
than host/auth/protocol). One live-API run, three GETs, fixtures
committed alongside this file.

## Probes run

| Probe | URL | Expected | Observed |
|-------|-----|----------|----------|
| Happy roster | `/v1/roster/TOR/20242025` | 200 | 200, 17,935 bytes JSON |
| Happy schedule | `/v1/club-schedule-season/TOR/20242025` | 200 | 200, 202,274 bytes JSON |
| Edge: relocated franchise | `/v1/roster/UTA/20232024` | 404 | 404, 367 bytes HTML |

User-Agent on all probes: `PuckBunny/0.1 (contact: crenshaw.jonathan@gmail.com)`.

## Findings

### 1. Roster payload shape

Top-level keys: `forwards`, `defensemen`, `goalies`. **No envelope, no
embedded `season` or `team`.** Three positionally-keyed lists; per-row
`positionCode` does the L/C/R distinguishing inside `forwards` and
the trivial `D`/`G` on the others.

Per-player fields confirmed across all groups: `id`, `firstName`,
`lastName`, `sweaterNumber`, `positionCode`, `shootsCatches`,
`heightInInches`, `weightInPounds`, `heightInCentimeters`,
`weightInKilograms`, `birthDate`, `birthCity`, `birthCountry`.

**Bio fields are present-but-optional.** In the TOR 2024-25 fixture,
`birthStateProvince` is present on roughly 70% of players across all
position groups (17/22 F, 11/15 D, 3/5 G) — likely a US/Canada vs.
international split, not a position-correlated thing. Schema must use
`extra="allow"` and avoid pinning anything beyond `id` and
`positionCode`.

**Implication for the loader:** The bronze envelope's `season` and
`team` columns must be propagated from request context, not parsed
from the response. `entity_id` is the team abbreviation.

### 2. Club-schedule-season payload shape

Top-level keys: `previousSeason`, `currentSeason`, `nextSeason`,
`clubTimezone`, `clubUTCOffset`, `games`. `currentSeason` matches the
requested season — usable as a defensive invariant
(`ClubScheduleSeasonMismatchError` raises if it doesn't).

`games` is a list of 101 entries for the TOR 2024-25 fixture, mixing
all three game types:

| `gameType` | Meaning | Count (TOR 2024-25) |
|------------|---------|---------------------|
| 1 | Preseason | 6 |
| 2 | Regular season | 82 |
| 3 | Playoffs | 13 |

All entries have `season=20242025`. `gameState` distribution at probe
time: `FINAL` × 6, `OFF` × 95 — consistent with a finished season
returned via the spike-§1 game-state convention.

Per-game keys overlap `ScheduleResponse`'s shape from PR-E
(`id`, `season`, `gameType`, `gameDate`, `gameState`, `awayTeam`,
`homeTeam`, plus `venue`, `tvBroadcasts`, etc.). PR-F2 deliberately
does not reuse `ScheduleGame` for `games[*]` — keeping the
inner-list typing as `list[dict[str, Any]]` means a per-game schema
regression on the club-schedule surface doesn't break ingest. Silver
M3 reconciles.

### 3. 404 contract

Requesting a `(team, season)` pair the franchise didn't exist for
returns **HTTP 404 with a `text/html` body** (not JSON). Spike fixture:
`roster_UTA_20232024_404.html` (367 bytes). The body is a plain Jetty
error page; unstructured.

**Implications for the loader:**

- The `RateLimitedClient.get` path already raises
  `httpx.HTTPStatusError` on 4xx (non-retryable). The loader catches
  it, checks `e.response.status_code == 404`, logs a warning, and
  returns `None` for that endpoint's `WriteResult` slot.
- Don't try to parse the 404 body as JSON; it isn't. Tests stub
  HTML bodies for the 404 path so this isn't an accidental
  ValidationError.
- Per-endpoint independent skip — if `/v1/roster/X/Y` 404s, we still
  attempt `/v1/club-schedule-season/X/Y`. The probe didn't separately
  test "roster 200 but schedule 404"; that's possible in principle
  and the loader handles it correctly.

### 4. Open-questions doc undercounted franchise events

The PR-F2 open-questions doc enumerated only the ARI → UTA relocation
(2024-25). For correctness of `team_abbrevs(season)` across the
2015-16 → present backfill window, **two more franchise events
matter**:

- **VGK** — Vegas Golden Knights, expansion in 2017-18. Adds 1 team.
- **SEA** — Seattle Kraken, expansion in 2021-22. Adds 1 team.

Resulting team-count by era:

| Seasons | Teams | Membership note |
|---------|-------|-----------------|
| 2015-16, 2016-17 | 30 | Base set |
| 2017-18 → 2020-21 | 31 | + VGK |
| 2021-22 → 2023-24 | 32 | + SEA |
| 2024-25+ | 32 | ARI → UTA (relocation, not expansion) |

`team_abbrevs(season)` enumerates these correctly; `endpoints.py`'s
docstring captures the same provenance.

### 5. What we did NOT probe

- **`/v1/roster/X/Y` for an in-progress season.** The TOR 2024-25
  roster captured here is for a completed season; mid-season roster
  shape may differ (e.g. injured-player flags, IR/recall metadata).
  M10's weekly maintenance loader will surface any drift.
- **Postponement reflection in `/v1/club-schedule-season/...`.** No
  postponed games existed in the TOR 2024-25 schedule at probe time.
  We don't know whether `gameState=PPD` games appear in this endpoint
  or whether they're elided. PR-F2 stays tolerant via
  `extra="allow"`; M3 reconciles.
- **ARI 2025-26 (post-relocation).** Symmetric to the UTA 2023-24
  case but not separately verified; loader's log-and-skip handles
  it identically regardless.

These are documented gaps, not blockers. Re-probe if anything
unexpected lands in M10's first weekly run.

## Fixtures committed

In `tests/ingestion/fixtures/team_season/`:

- `roster_TOR_20242025.json` — 17,935 bytes, verbatim API body.
- `club_schedule_season_TOR_20242025.json` — 202,274 bytes, verbatim
  API body.
- `roster_UTA_20232024_404.html` — 367 bytes, the literal 404 HTML.
  Reference artifact only; not used by tests (which stub their own
  HTML 404 body to avoid coupling the test to NHL's particular Jetty
  error template).
