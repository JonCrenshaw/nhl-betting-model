# Efficiency

Working principles for keeping the agentic workflow on PuckBunny lean and effective.

This is a meta-doc: it doesn't describe the code, it describes how Claude and Jon work together so that fresh sessions stay fast and the documentation stays load-bearing rather than ornamental.

---

## Core principle

The thing to optimize is **time-to-correct-action in a fresh session.**

Every doc and every piece of scaffolding either reduces that time (recipes, slash commands, `now.md`, repo map) or increases it (sprawling reference docs that Claude has to skim through).

Before adding any new doc, ask: "does this change what Claude does in the first three tool calls of a new session?" If not, it might be reference material that lives in a less-loaded place than `CLAUDE.md`.

The corollary: **docs that go stale are worse than missing.** Anything that requires manual maintenance needs an obvious owner moment — end-of-session for `now.md`, PR template for the repo map, milestone-close for the roadmap. If you can't name when it gets updated, don't write it.

---

## What "efficient scaffolding" looks like for PuckBunny

A well-tuned setup means a new Claude session reaches the right state in three tool calls:

1. Read `CLAUDE.md` — working agreements
2. Read `docs/now.md` — current state
3. Read whatever specific doc the session topic points at (a milestone plan, an ADR, a how-to)

If that's not happening — sessions are spending tool calls re-discovering structure, conventions, or recent decisions — the scaffolding has drifted.

---

## Review cadence

A formal scaffolding/efficiency review happens **at every milestone close**. The milestone-close moment is already a natural pause for retrospection (an exit-criteria gate has been met, a milestone PR has merged, work is shifting), so we piggy-back on that rhythm rather than inventing a separate timer.

The `/wrap` command in `.claude/commands/` reminds Jon when a milestone has just closed and offers to run the review.

### Review checklist

When triggered, the review walks these prompts:

1. **Stale doc audit.** For each tracked doc — `CLAUDE.md`, `docs/now.md`, `docs/roadmap.md`, `docs/gotchas.md`, `docs/working-with-claude.md`, the active milestone plan — when was it last updated, and does it still reflect reality? Flag anything that contradicts current code or current intent.
2. **Bloat audit.** Has `CLAUDE.md` grown past ~250 lines of unique content (excluding pointers)? If so, what can be moved to a less-loaded location? Same question for any single doc that has crossed a similar threshold.
3. **Slash command audit.** Are the existing commands in `.claude/commands/` still being used? Are there prompts Jon is typing repeatedly that should become commands? Cross-reference the parked ideas in `docs/ideas/efficiency-scaffolding-followups.md`.
4. **Parked ideas review.** Walk `docs/ideas/efficiency-scaffolding-followups.md`. Any item now justified by recent friction? If so, promote it. Any item parked for several reviews without justification? Delete it — indefinite parking is a smell.
5. **Time-to-correct-action smell test.** In the most recent two or three sessions, how many tool calls did Claude need before doing useful work? If it's drifting upward, something has slowed the startup.

### Output

A short note (5–15 lines) at the bottom of `docs/now.md` summarizing the review, with any follow-ups either landed in PRs or written into `docs/ideas/`. The note ages out — clear it when the next milestone closes.

---

## When *not* to add scaffolding

Resist adding a new doc, command, or piece of structure when:

- The pattern hasn't been done at least twice yet — premature recipes get the recipe wrong.
- The thing being documented changes faster than the doc can be updated.
- The information is already easy for Claude to derive from code (e.g., a hand-maintained table of dbt models when `dbt docs generate` exists).
- It would duplicate content that already lives in another doc — cross-link instead.

---

## Maintenance

This file is itself a working agreement. Update it in a small PR when the principles or review checklist change. Keep it short; bloat defeats the purpose.
