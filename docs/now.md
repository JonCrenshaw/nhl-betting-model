# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Branch: `feat/m2-pr-g-backfill` (uncommitted; Jon to commit via GitHub Desktop)
- Open PR: none

## Currently in flight

- PR-G plan ready to commit on `docs/m2-pr-g-plan` (working tree has uncommitted edits to `docs/milestones/m2-nhl-ingestion.md`)
- M2 PR-G implementation queued on `feat/m2-pr-g-backfill` (next, not started)

## Last session summary

- PR-G plan landed in `docs/milestones/m2-nhl-ingestion.md`. Added D8–D11 in "Open decisions and proposed answers": D8 commits to schedule day-walks via `DailyLoader.load_date` for game discovery (rejecting per-team fan-out and step-by-7); D9 adopts a single `backfill` subcommand with `--loader {games,season-summaries,team-season,all}` defaulting to `all`, with a durable note that PR-G should also extend `--season` on `team-season` and `season-summaries` to accept both `YYYY-YY` and `YYYYYYYY` for CLI consistency; D10 specifies end-of-phase + end-of-overall cost checks via `--cost-check {fail,warn,off}` (default `fail`, $5/mo threshold) and a sport-agnostic `src/puckbunny/ingestion/cost_check.py` module; D11 keeps PR-E's per-scope-unit dedupe and applies it to season-summaries and team-season via a per-loader gating table, with per-endpoint 404 log-and-skip on team-season writing manifest entries only for successful endpoints. Expanded PR-G entry in "Work breakdown" — branch `feat/m2-pr-g-backfill`, modules (`backfill.py`, `cost_check.py`, helpers in `endpoints.py` + `cli.py`), test surface (`test_backfill.py`, `test_cost_check.py`, `test_backfill_resume.py`, integration extension), working order, explicit out-of-scope (M10 cadence wiring, postponement detection, per-endpoint dedupe, ADR-0003). Estimate bumped from ~1 to ~1.5–2 days. PR-H entry expanded with a doc-hygiene checklist (architecture diagram refresh, endpoint inventory re-verify, franchise-event invariants in ADR-0003) deferred from PR-F1/F2/G; PR-H ADR scope bumped from D1–D7 to D1–D11. No code changes this session.

## Blocked

- _(none)_

## Next concrete step

- Commit PR-G plan on `docs/m2-pr-g-plan`, then begin PR-G implementation on `feat/m2-pr-g-backfill`. Working order per the expanded plan: orchestrator (`src/puckbunny/ingestion/nhl/backfill.py`) → `src/puckbunny/ingestion/cost_check.py` → CLI wiring (new `backfill` subparser + `_cmd_backfill` + `_default_backfill_factory`) → unit tests → resume test → CLI smoke → manual one-season live-API smoke (not committed). Remember to extend `--season` on existing `team-season` / `season-summaries` subparsers per D9. After PR-G, only PR-H (ADR-0003 covering D1–D11 + the doc-hygiene checklist) remains in M2.

---

## How this file is maintained

Claude updates this file as part of the end-of-session summary, every session, without being asked. The `/wrap` slash command in `.claude/commands/` is the canonical trigger.

Update rules:

- **Replace, don't append.** This file is current state, not a log. Git history is the log.
- One-line entries where possible; link to the relevant doc, ADR, or PR for detail.
- **If the session produced nothing substantive (no code changes, no new ADR, no doc landings), leave "Last session summary" as-is.** The most recent substantive summary should persist so a fresh session still sees the last meaningful context. Other fields ("Currently in flight," "Next concrete step," "Blocked") can still be updated if those facts changed during the session — e.g., a planning conversation might sharpen the next step or surface a new blocker without producing any code.
- If the active branch is `main`, leave "Open PR" as "none" rather than removing the line.
- The "Efficiency reviews" cadence in `docs/efficiency.md` may append a short review note at the bottom of this file at milestone close. Those notes age out — clear them when the next milestone closes.
