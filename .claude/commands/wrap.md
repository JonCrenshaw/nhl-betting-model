---
description: Wrap a session — summarize, update docs/now.md, and capture stray decisions.
---

## When to use

At the end of any session that produced changes — code, docs, ADRs, or even just a meaningful planning conversation. Run it before stepping away, not after.

## Why it exists

`docs/now.md` is the handoff to your future self (and to the next Claude session). If it doesn't get updated at session close, the next `/start` reads stale state and the session quality drops. This command is the canonical trigger for that update.

## Behavior

Wrap up this session in five steps:

### 1. Summarize what changed

A concise summary of:

- What was committed (and on which branch)
- What's still staged or unstaged in the working tree
- What the next natural step is
- Any decisions made during the session that should outlive it

### 2. Update `docs/now.md`

Edit the file to reflect current state. Replace, don't append — git history is the log; `now.md` is the snapshot.

- Active branch / PR
- Currently in flight
- Last session summary (one or two lines; replace if the session produced something substantive — see rule below)
- Blocked items, with reasons
- Next concrete step

If the session produced nothing substantive (no code changes, no new ADR, no doc landings), **leave "Last session summary" as-is** — the most recent substantive summary should persist so a fresh session still sees the last meaningful context. Other fields can still be updated if those facts changed during the session (e.g., "Currently in flight" if scope shifted, "Next concrete step" if the discussion produced a clearer next move, "Blocked" if a new blocker surfaced). Note any decisions in the relevant doc as usual.

### 3. Capture anything that should outlive the session

For each item that came up:

- **New architectural decision?** Draft an ADR in `docs/decisions/` (use `/new-adr`).
- **Stray idea not scoped for now?** Drop a file in `docs/ideas/`.
- **Roadmap shift (scope, ordering, dates)?** Update `docs/roadmap.md`.
- **New lesson learned the hard way?** Append to `docs/gotchas.md`.

### 4. Milestone-close check

If a milestone just closed in this session (exit criteria met, milestone PR merged, status updated to ✅ in the roadmap), remind Jon that `docs/efficiency.md` defines a milestone-close review cadence and ask whether he wants to run it now.

### 5. Recommend next commit

If there are uncommitted changes worth committing, propose a Conventional Commit message and a branch name following the convention in `CLAUDE.md`. Don't run `git` — Jon handles git operations in GitHub Desktop.
