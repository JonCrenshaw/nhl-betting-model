---
description: Start a session — load context and confirm the goal before any work.
---

## When to use

At the very top of any new session that's going to involve real work (code changes, ADRs, planning, debugging). Skip it for one-off questions that don't depend on project context.

## Why it exists

Every fresh Claude session starts with zero memory. This command runs the standard startup checklist from `CLAUDE.md` so you don't have to type the same setup prompt every time, and so the checklist actually gets followed (rather than skipped on busy days).

## Behavior

Read these files in order to load context for this session:

1. `CLAUDE.md` — working agreements and conventions
2. `docs/now.md` — current state of work (active branch/PR, what's in flight, blockers, next concrete step)
3. `docs/roadmap.md` — phase and active milestone
4. The most recently modified file in `docs/milestones/` if any milestone is in flight
5. Any ADR in `docs/decisions/` directly relevant to today's stated topic (skim only)
6. Any file in `docs/ideas/` directly relevant to today's stated topic (skim only)

Then, before writing any code or making any edits:

- Restate in one sentence what you understand the goal of this session to be
- Name the doc(s) you read that informed your understanding
- Ask Jon to confirm the goal before proceeding

If `docs/now.md` looks stale (the "Last session summary" doesn't match the most recent commits, or the "Next concrete step" appears to have already happened), flag it. Jon may need to brief you on what's changed, and the staleness itself is a signal that the last session didn't `/wrap` cleanly.
