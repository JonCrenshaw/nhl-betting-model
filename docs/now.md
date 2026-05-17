# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Branch: `main` (no active feature branch). PR-D (#44) and PR-E (#45) both merged.
- Open PR: none.

## Currently in flight

- Nothing — M3 PRs A–E all merged into main.

## Last session summary

- M3 PR-E merged (#45): `int_nhl__game_events` (CROSS JOIN UNNEST, ephemeral) + `fct_game_event` (sport-agnostic event table with generic event_type vocabulary). ST06 noqa on outer SELECT confirmed as sqlfluff false positive; gotcha documented.
- M3 PR-D merged (#44): `fct_game` (game spine) + `fct_game_outcome` (scores, winner, period_end, home_win).
- `gh` CLI installed at `C:\Program Files\GitHub CLI\gh.exe` — not on default PATH; add with `$env:PATH += ";C:\Program Files\GitHub CLI"` in PowerShell or configure permanently.

## Blocked

- `filter_ingestible` only filters on `game_state`, not `game_type` — non-competitive games (All-Star, 4 Nations) land in R2 until fixed. Staging WHERE clause is the current defense; ingestion-layer fix is a follow-up `fix:` PR.

## Next concrete step

- Start PR-F on a new branch: `int_nhl__game_skater_stats` + `int_nhl__game_goalie_stats` (intermediates parsing boxscore) + `fct_game_lineup` (union skaters + goalies). Plan in `docs/milestones/m3-silver-layer.md` (PR-F section). Branch: `feat/m3-pr-f-lineup`.

---

## How this file is maintained

Claude updates this file as part of the end-of-session summary, every session, without being asked. The `/wrap` slash command in `.claude/commands/` is the canonical trigger.

Update rules:

- **Replace, don't append.** This file is current state, not a log. Git history is the log.
- One-line entries where possible; link to the relevant doc, ADR, or PR for detail.
- **If the session produced nothing substantive (no code changes, no new ADR, no doc landings), leave "Last session summary" as-is.** The most recent substantive summary should persist so a fresh session still sees the last meaningful context. Other fields ("Currently in flight," "Next concrete step," "Blocked") can still be updated if those facts changed during the session — e.g., a planning conversation might sharpen the next step or surface a new blocker without producing any code.
- If the active branch is `main`, leave "Open PR" as "none" rather than removing the line.
- The "Efficiency reviews" cadence in `docs/efficiency.md` may append a short review note at the bottom of this file at milestone close. Those notes age out — clear them when the next milestone closes.

---

## M2 efficiency review (May 2026)

**Stale docs fixed:** `now.md`, `roadmap.md`, `milestones/m2-nhl-ingestion.md` — all described PR-H as in-flight after it had already merged. Root cause: session that shipped PR-H didn't `/wrap` after the merge.

**Bloat:** CLAUDE.md at 217 lines — within the 250-line budget, no action needed.

**Slash commands:** Promoted `/efficiency-review` from the ideas list; it now lives in `.claude/commands/`. All other commands (`/start`, `/wrap`, `/new-adr`, `/leakage-check`, `/calibration-check`) actively used.

**Parked ideas:** Recipe docs (`docs/how-to/`) approaching the promote threshold after 4+ ingestion patterns in M2 — flag at M3 close if another pattern is established. All other items remain parked with conditions unmet.

**Time-to-correct-action:** Stale `now.md` added one extra read hop this session. Fix: keep `/wrap` discipline. Target remains ≤3 tool calls to orient.
