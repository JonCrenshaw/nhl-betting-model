# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Branch: none (on `main`). M3 PR-B merged May 2026.
- Open PR: none.

## Currently in flight

- M3 PR-C starting: `int_nhl__team_spine`, `dim_team`, `int_nhl__player_spine`, `dim_player`. Plan in `docs/milestones/m3-silver-layer.md` (PR-C section). Key complexity: franchise event mapping (ARI→UTA, VGK expansion, SEA expansion) in `int_nhl__team_spine`.

## Last session summary

- M3 PR-B merged (PR #40). Eight `stg_nhl__*` staging views shipped: `landing`, `boxscore`, `play_by_play`, `skater_summary`, `goalie_summary`, `team_summary`, `roster`, `club_schedule_season`. Hotfix commit followed (`fix(m3): ST06 column order in stg_nhl__roster`). DuckDB JSON extraction conventions from D6 established across all models.

## Blocked

- `filter_ingestible` only filters on `game_state`, not `game_type` — non-competitive games (All-Star, 4 Nations) land in R2 until fixed. Staging WHERE clause is the current defense; ingestion-layer fix is a follow-up `fix:` PR.

## Next concrete step

- Start PR-C on branch `feat/m3-pr-c-dim-team-player`. Build order per milestone plan: `int_nhl__team_spine` first (franchise event mapping), then `dim_team`, then `int_nhl__player_spine`, then `dim_player`. Tests: unique + not_null on `team_id` / `player_id`; relationships to `dim_league`.

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
