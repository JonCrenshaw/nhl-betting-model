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

### 5. Commit, push, and merge

This step happens in order — wrap must complete before the feature PR merges so that `main` is immediately correct with no follow-up PR.

1. **Commit housekeeping changes** — stage and commit any updates to `docs/now.md`, `docs/gotchas.md`, `docs/roadmap.md`, ADRs, or `.claude/settings.local.json` as a `chore: wrap <milestone> <PR> session` commit on the current feature branch.
2. **Push** — `git push` so the chore commit is on the remote branch before the PR merges.
3. **Ask Jon to confirm CI is green** — do not merge until confirmed.
4. **Merge the PR** — once CI is green, run `gh pr merge --merge` (or `--squash` if that's the repo convention). This brings the updated `now.md` into `main` in the same merge as the feature code.

If there is no open PR (planning-only session, or the session produced only housekeeping changes), skip the merge step and note the pending commit so the next session can open or update the PR.
