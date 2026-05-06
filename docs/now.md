# Now

The current state of work on PuckBunny. Updated by Claude at the end of every session.

This is the fastest way for a fresh Claude session to learn where we left off. It is read at the top of every session as part of the startup checklist in `CLAUDE.md`.

Keep this file under ~80 lines. If it grows beyond that, content has either gone stale or belongs in `docs/roadmap.md`, an ADR, or a `docs/ideas/` file.

---

## Active branch / PR

- Branch: `main`
- Open PR: none

## Currently in flight

- M2 PR-F: season-scoped loaders (planned, not started)

## Last session summary

- Initial scaffolding pass for agentic-efficiency tooling: created `docs/now.md`, `docs/gotchas.md`, `docs/efficiency.md`, `docs/ideas/efficiency-scaffolding-followups.md`, and the first batch of slash commands in `.claude/commands/` (`/start`, `/wrap`, `/new-adr`, `/leakage-check`, `/calibration-check`). Pulled cross-mount file safety and dev-container guidance out of `CLAUDE.md` into `docs/gotchas.md` and added pointers + an "Efficiency reviews" section to `CLAUDE.md`.

## Blocked

- _(none)_

## Next concrete step

- Begin M2 PR-F (season-scoped loaders). See `docs/milestones/m2-nhl-ingestion.md`.

---

## How this file is maintained

Claude updates this file as part of the end-of-session summary, every session, without being asked. The `/wrap` slash command in `.claude/commands/` is the canonical trigger.

Update rules:

- **Replace, don't append.** This file is current state, not a log. Git history is the log.
- One-line entries where possible; link to the relevant doc, ADR, or PR for detail.
- **If the session produced nothing substantive (no code changes, no new ADR, no doc landings), leave "Last session summary" as-is.** The most recent substantive summary should persist so a fresh session still sees the last meaningful context. Other fields ("Currently in flight," "Next concrete step," "Blocked") can still be updated if those facts changed during the session — e.g., a planning conversation might sharpen the next step or surface a new blocker without producing any code.
- If the active branch is `main`, leave "Open PR" as "none" rather than removing the line.
- The "Efficiency reviews" cadence in `docs/efficiency.md` may append a short review note at the bottom of this file at milestone close. Those notes age out — clear them when the next milestone closes.
