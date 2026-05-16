# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Worktree `peaceful-albattani-94ee85`: M3 PR-C (dim_team + dim_player) — ready to open PR.
- Main repo: Pydantic fix in `src/puckbunny/ingestion/nhl/schemas.py` — unstaged, needs its own `fix:` commit.

## Currently in flight

- M3 PR-C: `int_nhl__team_spine`, `int_nhl__player_spine`, `dim_team`, `dim_player` — dbt build passes prod, sqlfluff clean. PR not yet opened.

## Last session summary

- Completed M3 PR-C: 4 new dbt models (team + player dimension spine + dims). Fixed staging game_type filter (WHERE game_type IN (2,3) in landing/boxscore/play-by-play) to exclude All-Star/4 Nations/Olympics. Fixed all 7 dbt 1.11.8 deprecated test syntax warnings in staging schema.yml. Fixed Pydantic bug in `ScheduleGame` (gameDate optional for preseason entries). Ran M2 2024-25 backfill — all 6 endpoints now in R2, 1,510 games loaded. Full prod `dbt build` passes clean.

## Blocked

- `filter_ingestible` only filters on `game_state`, not `game_type` — non-competitive games (All-Star, 4 Nations) land in R2 until fixed. Staging WHERE clause is the current defense; ingestion-layer fix is a follow-up `fix:` PR.

## Next concrete step

1. **Commit Pydantic fix** in main repo as `fix(ingestion): make ScheduleGame.gameDate optional for preseason entries`.
2. **Open PR-C** from worktree branch — title: `feat(warehouse): dim_team and dim_player (M3 PR-C)`.
3. **Start PR-D**: `fct_game` + `fct_game_outcome` on a new worktree off `feat/m3-pr-d-fct-game`.

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
