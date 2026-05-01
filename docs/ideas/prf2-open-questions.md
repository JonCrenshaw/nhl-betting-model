# PR-F2 open questions (parked from PR-F1 retrospective, 2026-05-01)

Three design questions PR-F2 needs to answer in its planning phase
*before* writing code. Surfaced during the PR-F1 commit-out
conversation so the next session doesn't have to re-derive them.
None are blockers — they're shape choices the M2 doc and the spike
notes deliberately left open.

---

## 1. Team enumeration

PR-F2 needs to drive a per-team loop for both endpoints
(`/v1/roster/{TEAM}/{SEASON}` and
`/v1/club-schedule-season/{TEAM}/{SEASON}`). Three options:

**(a) Hardcoded constant** in `endpoints.py`, e.g.
`NHL_TEAM_ABBREVS: frozenset[str]`. Simplest. But it drifts when
teams move/rename, and it needs to be **season-aware** to handle
historical backfill correctly:

| Change | Old → New | Effective season |
|--------|-----------|------------------|
| Arizona → Utah | ARI → UTA | 2024-25 |
| Atlanta → Winnipeg | ATL → WPG | 2011-12 (before our backfill) |
| Phoenix → Arizona | PHX → ARI | 2014-15 |

For our backfill window (2015-16 → present), the only relevant
change is ARI → UTA in 2024-25. Every other change predates 2015-16.
A constant `NHL_TEAM_ABBREVS_BY_SEASON: dict[str, frozenset[str]]`
or a function `team_abbrevs(season) -> frozenset[str]` works.

**(b) Discover from `/v1/standings/now`** at run time. Always current
for *the current season*. Doesn't help historical seasons (the
endpoint reflects whatever the current league looks like).

**(c) Discover from previously-fetched schedule data** (per-game
`awayTeam.abbrev` / `homeTeam.abbrev` from PR-E's daily walker
outputs). Naturally season-correct. But couples PR-F2 to whether
PR-G's backfill has run game-level ingestion first.

**Lean.** Option (a) with a season-aware lookup. Quiet, no
dependency on other layers, easy to add the one ARI→UTA exception
in code with a comment. Revisit if a future season change makes the
hand-maintained constant burdensome.

**Defensive consideration.** Whatever we choose, the loader needs
graceful 404 handling for `(team, season)` pairs that didn't exist
(e.g. requesting UTA roster for 2023-24, or ARI roster for
2025-26). Probably "log and skip" rather than "raise" so a backfill
loop doesn't abort partway through.

---

## 2. Loader and file shape

The M2 doc says PR-F2 lives in `roster.py` and covers both
`/v1/roster/...` and `/v1/club-schedule-season/...`. Two endpoints
in one file named after one of them is awkward. Options:

**(a) Keep `roster.py`** — document at top that it covers both
endpoints (mild abuse of naming).

**(b) Rename to `team_season.py`** (or `team.py`) — generalizes
naming for both endpoints. Matches PR-F1's `season_summaries.py`
convention of "named for the scope, not for one endpoint."

**(c) Split into `roster.py` and `club_schedule.py`** — one loader
per endpoint, no naming awkwardness. But two loaders means two CLI
subcommands, two test files, two factories — more boilerplate for
two endpoints that share the same scope key.

**Lean.** Option (b). PR-F1's `SeasonSummariesLoader.load_one(season)`
hits three endpoints in one file named after the scope; the parallel
shape for PR-F2 is `TeamSeasonLoader.load_one(season, team)` hitting
two endpoints in `team_season.py`. The M2 doc's "roster.py" naming
predates PR-F1's precedent — worth deviating, with a one-line
mention in the PR description so the doc/code drift is intentional.

---

## 3. scope_key and cadence (and the M10 implications)

The M2 doc pins `scope_key = f"{season}|{team_abbrev}"` for
PR-F2's manifest entries. That's correct for backfill: one entry per
`(endpoint, season, team)` tuple, manifest-gateable.

Cadence is **less uniform than PR-F1's** because the two endpoints
inside PR-F2 evolve differently:

| Endpoint | What changes | Reasonable cadence |
|----------|--------------|--------------------|
| `/v1/roster/{TEAM}/{SEASON}` | Trades, callups, IR, suspensions | Weekly; **daily** in the ~2-week trade-deadline window |
| `/v1/club-schedule-season/{TEAM}/{SEASON}` | Postponements (rare), reschedules | Once per season after schedule release; ad-hoc on postponement |

So PR-F2's loader is mixing two endpoints with different natural
cadences. PR-F1's "loader is cadence-agnostic, M10 schedules" pattern
applies — the loader doesn't need to care — but M10 will need *three*
distinct schedules for PR-F2:

1. **Backfill** (PR-G): `manifest.has(endpoint, scope_key)` gate;
   one-shot per `(season, team, endpoint)`.
2. **Weekly + trade-deadline-daily roster** for the in-progress
   season: bypass gating (same pattern as PR-F1 weekly summaries).
3. **Post-schedule-release club-schedule** for the upcoming season:
   gate via `manifest.has()` — once per `(season, team)` is correct
   and re-fetch is wasteful unless a postponement triggers it.

When PR-F2 lands, **park the M10 cadence design in
`docs/ideas/team-season-cadence-gating.md`** (sister to PR-F1's
`season-summaries-cadence-gating.md`). Don't try to solve M10 in
PR-F2 itself — keep the loader cadence-agnostic per the PR-F1
precedent.

---

## What this means for PR-F2 planning

These three questions don't change the work breakdown — PR-F2 is
still one PR landing roster + club-schedule-season fetchers +
manifest-aware bronze writes + tests + CLI. They're *shape* choices
that need explicit calls in the planning phase, before code lands.

Suggested order in next session's planning response:

1. State the three decisions (team enumeration, file/loader shape,
   cadence parking) with rationale.
2. Then propose branch name + PR plan as usual.
