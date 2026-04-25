# PR-A spike notes — one-game NHL API ingest

**Branch.** `spike/nhl-api-one-game` (throwaway, not for merge to main; cherry-pick this notes file when consuming).
**Date.** 2026-04-25.
**Goal.** Validate the M2 plan against live `api-web.nhle.com` payloads before writing PR-B (HTTP client + storage primitives) and PR-C/D (NHL game + PxP loaders). See `docs/milestones/m2-nhl-ingestion.md`.

---

## What ran

`tools/spike/pra_one_game.py` (PEP 723 inline-deps script, run with `uv run --no-project`):

1. Walked recent dates against `/v1/schedule/{YYYY-MM-DD}` until it found a `FINAL`/`OFF` regular-season or playoff game.
2. GET'd `/v1/gamecenter/{id}/landing`, `/v1/gamecenter/{id}/boxscore`, and `/v1/gamecenter/{id}/play-by-play`.
3. Wrote each response into the proposed bronze typed-envelope-plus-raw-JSON Parquet shape (one row per file).
4. Re-opened each Parquet with DuckDB and probed the response body.

**Game chosen.** `id=2025030123` — Tampa Bay Lightning at Montreal Canadiens, 2026-04-24, season `20252026`, `gameType=3` (playoffs), `gameState=OFF`. First-round playoff opener landed in the candidate window. A regular-season game would have been a slightly better fixture; not material for shape validation.

---

## Confirmations of the M2 plan

| Plan item | Status |
|-----------|--------|
| **D1.** `api-web.nhle.com` is reachable, returns 200s for all three game-level endpoints, accepts our identifying `User-Agent`, no auth required. | Confirmed. |
| **D3.** Typed-envelope-plus-raw-JSON row shape (`game_id`, `season`, `game_date`, `endpoint`, `endpoint_params_json`, `fetched_at_utc`, `response_json`, `response_sha256`) writes cleanly to Parquet via pyarrow. zstd compression is effective. | Confirmed. |
| **D6.** Friendly UA + plain `httpx` GET works without rate-limiter or retries. (Polite posture is fine; we add the rate-limiter in PR-B as planned, not because anything pushed back.) | Confirmed. |
| **Endpoint key fields exist.** `id`, `season` (string `"20252026"`), `gameType`, `gameDate` (`'YYYY-MM-DD'`), `gameState`, `startTimeUTC`, `awayTeam`, `homeTeam` are all present on at least the landing payload. | Confirmed — all populate the typed envelope columns directly. |

### Storage / cost data points

Per-game compressed Parquet sizes (zstd, single row, with raw JSON in a `large_string` column):

| Endpoint | Response JSON | Parquet | Compression |
|----------|--------------:|--------:|------------:|
| landing | 13.7 KB | 5.7 KB | ~2.4× |
| boxscore | 13.7 KB | 5.5 KB | ~2.5× |
| play-by-play | 131.2 KB | 15.9 KB | **~8.3×** |

Extrapolating to the M2 backfill scope (~13,000 games over 2015–16 → 2025–26):

- landing total ≈ 73 MB
- boxscore total ≈ 72 MB
- play-by-play total ≈ 207 MB
- **Bronze game-level total ≈ ~350 MB**

At Cloudflare R2's $0.015/GB/month list price that's ≈ **$0.005/month**, three orders of magnitude below the $5/month alert threshold in the M2 plan. (Plan's earlier estimate of "PxP ~100 KB/game" was conservative; observed is ~16 KB/game compressed.) No reason to revisit D2 or the cost section.

---

## Surprises and things worth knowing before PR-B/C/D

### 1. `gameState` returns `OFF` for finished playoff games, not `FINAL`

The schedule endpoint returned `gameState='OFF'` for the playoff game we ingested, even though the game is concluded. The spike script accepted both `FINAL` and `OFF`, and `docs/milestones/m2-nhl-ingestion.md` already references "FINAL" as the daily-loader gate. **Action for PR-E**: treat `{FINAL, OFF}` as the "done, ingestible" state set, not just `FINAL`. Anything else (`LIVE`, `FUT`, `PRE`, `CRIT`) should be skipped. Worth a constant in `endpoints.py`.

### 2. The three endpoints overlap heavily but each has unique top-level fields

All three carry the bulk of game metadata (`id`, `season`, `gameType`, `gameDate`, `gameState`, `awayTeam`, `homeTeam`, `venue`, `periodDescriptor`, etc.). On top of that:

- `landing` is the only one with `venueTimezone` and `tiesInUse`.
- `boxscore` adds `gameOutcome` and `playerByGameStats` (the actual reason to fetch it).
- `play-by-play` adds `plays`, `rosterSpots`, `displayPeriod`, `gameOutcome`.

**Action for PR-C schemas.py.** Don't try to model a single canonical "game" pydantic schema with all-optional fields; model each endpoint separately and let silver (M3) reconcile. The shared subset is small enough that a `BaseGameEnvelope` mixin works, but per-endpoint `LandingResponse`, `BoxscoreResponse`, `PlayByPlayResponse` is the right unit.

### 3. `rosterSpots` is on play-by-play, not boxscore

Mildly surprising — boxscore has `playerByGameStats` (per-player game stats split into `awayTeam.{forwards,defense,goalies}` and same for home), but the per-game roster (every player on the bench, with `playerId`/`teamId`/`positionCode` etc.) lives in the **play-by-play** payload, not the boxscore. Means PR-D will deliver the roster pull "for free" alongside PxP. **No action needed**, just note this when M3 builds the silver `event` and `lineup` tables.

### 4. `playerByGameStats` shape is well-behaved

Both teams returned `12 forwards / 6 defense / 2 goalies` — the standard NHL 20-skater dressed roster + 2 goalies. Each is a list of player-stat dicts. Nothing weird; a straightforward unnest in dbt at the silver layer.

### 5. PxP `plays[0]` has no `details` block

The first play in the array has only structural keys (`eventId`, `periodDescriptor`, `situationCode`, `sortOrder`, `timeInPeriod`, `timeRemaining`, `typeCode`, `typeDescKey`, `homeTeamDefendingSide`). It's likely a period-start type that legitimately has no details. The probe didn't sample event-type-specific fields, but the type histogram showed `shot-on-goal=41`, `hit=67`, `faceoff=48`, etc. — so spatial/coordinate data should be inside `plays[i].details` on those event types.

**Action for PR-D.** Before locking the PxP parser, scan the union of `plays[*].details` keys across event types on the saved Parquet (this spike's bytes are good enough to start; no need to refetch). Specifically confirm that `xCoord`/`yCoord` are present on shooting events and that `eventOwnerTeamId` / `losingPlayerId`+`winningPlayerId` (or equivalent) are present on faceoffs. The PxP layout has changed at NHL.com migrations before, so the canonical-keys assumption is a known risk.

### 6. Top-level keys vary slightly between endpoints — update plan's column comment

In M2's D3 the natural-key column is described as "`game_id` or `entity_id`". For all three endpoints the response carries an integer `id` field that is the game id, and the schedule endpoint also returns it. **Action for PR-C.** Use `id` as the canonical natural-key field name in the typed envelope. No schema change needed — `game_id` is fine as the column name; just clarify in code comments that it sources from `response.id`.

### 7. Game ID format — useful for natural partitioning later

`2025030123` decomposes as `{season_start_year=2025}{game_type=03}{game_seq=0123}`. Confirms the well-known NHL ID encoding. Not an action item, but a handy assertion to add to the schedule loader as a sanity check (`assert game_id // 1_000_000 == int(season[:4])`), which would catch upstream API encoding changes early.

---

## Open questions / parked

- **Schedule endpoint actually returns a *week* of games**, not just the requested date — its top-level key is `gameWeek`, an array of day-objects. The current daily-loader sketch in PR-E should iterate `gameWeek[*].games` filtered to the requested date, *not* hand-walk a single day. The cost is one identical extra payload per fetch (cheap), the benefit is consistent code and the option to back-collapse a missed day.
- **`api.nhle.com/stats/rest/v1/...`** wasn't exercised by this spike. Adding it for PR-F (season summaries / rosters) is unchanged risk — but worth one similar one-shot probe before PR-F starts.
- **Did not retry / pause / inspect 429 behavior.** The spike was three GETs total. PR-B's rate-limited client + tenacity retries still need a real-world stress test; we can synthesize one by hammering the schedule endpoint at e.g. 10 req/sec briefly, or just trust the polite default.

---

## Recommendation

**Proceed to PR-B as planned, with these edits to the M2 plan / future PRs:**

1. PR-C: per-endpoint pydantic models, not a single shared one. (#2 above.)
2. PR-D: before writing the parser, scan the captured PxP Parquet for the union of `plays[*].details` keys per event type. (#5.)
3. PR-E: state filter is `{"FINAL", "OFF"}`, schedule walks `gameWeek[*]` not a single day. (#1, #7-bullet.)
4. PR-F: budget a 30-minute probe of `api.nhle.com/stats/rest/v1` analogous to this spike before committing to the schemas. (Open question above.)

None of these are plan-breakers. D1–D7 stand. Cost projection improves; storage layout is unchanged.
