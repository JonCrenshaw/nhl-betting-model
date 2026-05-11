# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Branch: `feat/m2-pr-g-backfill` (uncommitted; Jon to commit via GitHub Desktop)
- Open PR: none

## Currently in flight

- M2 PR-G: backfill CLI + manifest gating (implementation complete, awaiting Jon to run pytest on Windows + open PR)

## Last session summary

- M2 PR-G implementation complete on local working tree. Three planning Qs resolved upfront: (Q1) thread one `run_id` through every phase including `DailyLoader.load_date` via a new optional kwarg; (Q2) drop the separate end-of-overall cost-check pass — the last phase's check is the end-of-overall; (Q3) single `backfill_factory` test seam returning a `BackfillCollaborators` struct. Plus an unblocked D9 follow-through: extended `format_season_id` to accept `YYYY-YY` alongside the 8-digit form (with consecutive-year validation in both branches), so `--season`, `--from-season`, `--to-season` all take both shapes across every subcommand. Also fixed `SeasonSummariesLoader.load_one`'s `str(season)` → `format_season_id(season)` so the bronze envelope's `season` column lands canonical regardless of CLI input shape. Added `src/puckbunny/ingestion/cost_check.py` (sport-agnostic; `compute_projection` + `evaluate` with `{fail,warn,off}` modes, env-overridable `INGEST_COST_CHECK_THRESHOLD_USD` defaulting to $5/mo, `R2_STORAGE_USD_PER_GB_MONTH=0.015`) and `src/puckbunny/ingestion/nhl/backfill.py` (phase functions + `run_backfill` dispatcher, `BackfillCollaborators` frozen dataclass, end-of-phase cost-check, phase order team-season → season-summaries → games when `--loader=all`). CLI: `backfill --from-season SEASON --to-season SEASON [--loader {games,season-summaries,team-season,all}] [--cost-check {fail,warn,off}] [--ingest-date YYYY-MM-DD]`; cost-check trip returns exit code 2. New tests: `test_nhl_endpoints.py` (format_season_id + parse_season_range + dates_in_season), `test_cost_check.py`, `test_backfill.py` (orchestrator + CLI), `test_backfill_resume.py` (real-loader resume scenarios), `test_smoke_integration.py` (live-API marker). `ruff check` + `ruff format` clean; `py_compile` clean. Pytest not yet run — Jon to verify on Windows.

## Blocked

- _(none)_

## Next concrete step

- Jon re-runs `uv run pytest` on Windows to confirm the 5 fixed failures now pass (CLI JSON-line extraction, tripped-projection for the unknown-mode branch, "abcdefgh" replacing "2024-25" in two pre-existing malformed-season tests since YYYY-YY is now valid). Once green, open PR-G against `main`. Suggested PR title: `feat(ingestion): backfill orchestrator + cost-check tripwire (M2 PR-G)`. PR description should explicitly call out the `format_season_id` `YYYY-YY` extension as a cross-subcommand behavior change (per D9), and note that the cost-check default of $5/mo is a tripwire (~3 orders of magnitude inside the M2 plan's $50/mo ceiling) not a brake. After PR-G merges, only PR-H (ADR-0003 capturing D1–D11 + warehouse doc refresh) remains in M2.

---

## How this file is maintained

Claude updates this file as part of the end-of-session summary, every session, without being asked. The `/wrap` slash command in `.claude/commands/` is the canonical trigger.

Update rules:

- **Replace, don't append.** This file is current state, not a log. Git history is the log.
- One-line entries where possible; link to the relevant doc, ADR, or PR for detail.
- **If the session produced nothing substantive (no code changes, no new ADR, no doc landings), leave "Last session summary" as-is.** The most recent substantive summary should persist so a fresh session still sees the last meaningful context. Other fields ("Currently in flight," "Next concrete step," "Blocked") can still be updated if those facts changed during the session — e.g., a planning conversation might sharpen the next step or surface a new blocker without producing any code.
- If the active branch is `main`, leave "Open PR" as "none" rather than removing the line.
- The "Efficiency reviews" cadence in `docs/efficiency.md` may append a short review note at the bottom of this file at milestone close. Those notes age out — clear them when the next milestone closes.
