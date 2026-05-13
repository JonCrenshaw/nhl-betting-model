# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Branch: `claude/ecstatic-tu-f78712` (rename to `feat/m3-pr-a-infra` at commit time). M2 closed May 2026.
- Open PR: none yet — PR-A ready to commit.

## Currently in flight

- M3 PR-A. All deliverables built and locally verified: `docs/infrastructure/motherduck.md` runbook, `dbt/models/core/README.md`, `dbt/seeds/dim_sport.csv` + `dim_league.csv` + `schema.yml`, `.env.example` updated. `dbt debug --target prod` against MotherDuck and `dbt seed && dbt test --select dim_sport dim_league` against dev DuckDB both green.

## Last session summary

- M3 PR-A built. MotherDuck provisioned (database `puckbunny`, region us-west-2). Initial token leaked into untracked `docs/infrastructure/motherduck.md` was rotated; new token in `.env`. Wrote proper motherduck.md runbook (mirrors r2.md), created `dbt/models/core/` scaffold, created `dim_sport` + `dim_league` seeds with YAML descriptions and unique/not_null/relationships tests. All 12 dbt tests pass locally.

## Blocked

- None. Ready to commit PR-A and open the GitHub PR.

## Next concrete step

- Jon: commit PR-A as `feat/m3-pr-a-infra`, open PR, merge. Then start PR-B (staging layer — eight `stg_nhl__*` models) per `docs/milestones/m3-silver-layer.md`.

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
