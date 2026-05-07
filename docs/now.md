# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Branch: `main`
- Open PR: none

## Currently in flight

- M2 PR-G: backfill CLI + manifest gating (next, not started)

## Last session summary

- M2 PR-F2 landed and merged to `main`. `TeamSeasonLoader` covers `/v1/roster/{TEAM}/{SEASON}` and `/v1/club-schedule-season/{TEAM}/{SEASON}` on `api-web.nhle.com`; one bronze envelope per fetch with per-endpoint log-and-skip on 404 and a defensive `currentSeason` invariant. Inline first-commit probe (no separate spike PR) recorded fixtures for TOR 2024-25 + UTA 2023-24 (the 404 case). Added season-aware `team_abbrevs(season)` enumerating 30/31/32/32 across the four backfill-window eras (the open-questions doc undercounted franchise events — VGK 2017-18 and SEA 2021-22 also matter). CLI: `team-season --season SEASON [--team TEAM]`, defaulting to all teams. Renamed `_format_season_id` and `_normalize_team_abbrev` to public for cross-loader reuse. M10 cadence design parked in `docs/ideas/team-season-cadence-gating.md` (three schedules: backfill gated, weekly+trade-deadline-daily roster bypassing gating, post-schedule-release club-schedule gated). 138 tests green, ruff clean.

## Blocked

- _(none)_

## Next concrete step

- Begin M2 PR-G (backfill CLI + manifest gating). PR-G is the backfill side of the manifest-gating story PR-F1 and PR-F2 pre-locked in their cadence-gating docs (`docs/ideas/season-summaries-cadence-gating.md`, `docs/ideas/team-season-cadence-gating.md`). Open shape questions to call upfront in the planning response: (a) game discovery — schedule day-walks vs. per-team fan-out via club-schedule-season; (b) single `backfill` subcommand vs. per-loader subcommands; (c) cost-check methodology per Risk #4 in M2 doc; (d) resumability granularity — keep PR-E's per-game-not-per-endpoint dedupe or revisit. Branch: `feat/m2-pr-g-backfill`. After PR-G, only PR-H (ADR-0003 + warehouse doc updates) remains in M2.

---

## How this file is maintained

Claude updates this file as part of the end-of-session summary, every session, without being asked. The `/wrap` slash command in `.claude/commands/` is the canonical trigger.

Update rules:

- **Replace, don't append.** This file is current state, not a log. Git history is the log.
- One-line entries where possible; link to the relevant doc, ADR, or PR for detail.
- **If the session produced nothing substantive (no code changes, no new ADR, no doc landings), leave "Last session summary" as-is.** The most recent substantive summary should persist so a fresh session still sees the last meaningful context. Other fields ("Currently in flight," "Next concrete step," "Blocked") can still be updated if those facts changed during the session — e.g., a planning conversation might sharpen the next step or surface a new blocker without producing any code.
- If the active branch is `main`, leave "Open PR" as "none" rather than removing the line.
- The "Efficiency reviews" cadence in `docs/efficiency.md` may append a short review note at the bottom of this file at milestone close. Those notes age out — clear them when the next milestone closes.
