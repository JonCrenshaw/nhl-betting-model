## When to use

At every milestone close, immediately after the milestone PR merges and before starting the next milestone. Also useful any time sessions feel slow to orient or docs feel out of date.

## Why it exists

The efficiency review is the milestone-close checkpoint for keeping the scaffolding lean and load-bearing. Without a prompt, it gets skipped. This command makes it a first-class habit rather than an afterthought.

## Behavior

Walk the five-item checklist from `docs/efficiency.md` in order:

### 1. Stale doc audit

Read each of these and check whether it reflects current reality:

- `CLAUDE.md` — working agreements. Does the folder structure match the repo? Do any conventions reference tools or patterns that no longer apply?
- `docs/now.md` — does the active branch/PR match what `git log` shows? Does the "Next concrete step" describe something that already happened?
- `docs/roadmap.md` — are milestone statuses (✅ / 🟡 / ⬜) accurate? Does the "Current status" paragraph match the most recent commits?
- `docs/gotchas.md` — any entries that are now resolved upstream and can be deleted?
- `docs/working-with-claude.md` — any conventions that have changed?
- The active milestone plan in `docs/milestones/` — does the status line and PR checklist reflect what's actually merged?

Flag every staleness found. Fix it (or note it can't be fixed without Jon's input).

### 2. Bloat audit

- Is `CLAUDE.md` past ~250 lines of unique content? If so, what can move to a less-loaded location?
- Any other doc that has grown past a similar threshold without a clear reason?

### 3. Slash command audit

- List the commands in `.claude/commands/`.
- Are any going unused? (Signs: the workflow they cover hasn't come up in several milestones.)
- Is Jon typing the same multi-line prose into multiple sessions? If so, name it as a candidate for a new command.
- Cross-reference `docs/ideas/efficiency-scaffolding-followups.md` for queued candidates.

### 4. Parked ideas review

Read `docs/ideas/efficiency-scaffolding-followups.md`. For each item:

- Has its "Promote when" condition now been met? If yes, promote it.
- Has it been parked through several reviews without anyone reaching for it? If yes, delete it and say why.

### 5. Time-to-correct-action smell test

In the most recent two or three sessions, how many tool calls elapsed before Claude did useful work? The target is ≤3. If it's drifting upward, name what caused the extra hops and propose a fix.

---

## Output

At the end:

1. Make any doc fixes that are clearly correct (stale statuses, stale branch names, promoted items).
2. Append a short note (5–15 lines) to the bottom of `docs/now.md` under a heading `## <Milestone> efficiency review (<Month> <Year>)`. Summarize findings and any follow-ups. This note ages out — it will be cleared at the next milestone close.
3. Recommend a branch name and commit message for the doc changes so Jon can commit them in GitHub Desktop.
