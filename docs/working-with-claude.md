# Working with Claude

How Jon and Claude collaborate on PuckBunny across sessions. This is the companion to `CLAUDE.md`: that file tells Claude how to behave on this codebase; this file tells Jon how to get the most out of Claude.

Read this once. Revisit when a session feels off the rails.

---

## Core model: docs are Claude's memory

Claude does not persist anything between sessions on its own. Every new conversation starts with zero recollection of prior ones. The repo is the memory: `CLAUDE.md`, `docs/roadmap.md`, `docs/decisions/`, `docs/ideas/`, and now this file.

This has two consequences:

1. **If a decision isn't written down, it didn't happen.** Verbal agreements evaporate between sessions. Anything that should survive needs to land in a doc or an ADR before the session ends.
2. **Session quality is bounded by the docs.** A well-structured repo means any new session can get up to speed in three tool calls. A poorly maintained one means Claude rediscovers the wheel every time.

The implication: treat documentation as load-bearing infrastructure, not as overhead.

---

## When to start a new session vs. continue

**Start a new session when:**
- The prior session wrapped a discrete chunk of work (a PR merged, an ADR written, a milestone closed).
- You're switching topics — going from "architecture planning" to "debug a dbt model" is a clean break.
- The current session has run long and responses are getting sluggish or you feel context drift.
- A day or more has passed since the last message.

**Continue the current session when:**
- You're mid-task and context is still fresh and relevant.
- The next step is a direct continuation of what just happened (e.g., "now add tests for that function").
- You're iterating on something where Claude has just read the relevant files.

When in doubt, start fresh. The cost of a clean start is low; the cost of a confused session dragging on is high.

---

## Opening a new session well

At the top of a new session, the single most useful message is one sentence of intent plus a pointer to where the relevant context lives. Claude's `CLAUDE.md` already instructs it to read that file and the roadmap, so you don't need to repeat that.

Good session openers:

> "Working on M1 today. Goal is to scaffold `src/` with the first NHL API loader. Read the roadmap for M1 specifics first."

> "Reviewing the warehouse ADR before we write code. Skim `docs/decisions/0001-warehouse-stack.md` and tell me what you'd push back on."

> "Need to add a dbt model for staging NHL schedule data. Follow the naming conventions in `CLAUDE.md` and put it in `dbt/models/staging/nhl/`."

What makes these work:
- They state the goal in one line.
- They name the milestone, ADR, or convention document that matters.
- They don't try to re-explain the whole project.

Avoid:
- "Let's work on PuckBunny" — too vague; Claude will ask clarifying questions you don't need to answer if you just say what you want.
- Dumping the entire project context at the top — `CLAUDE.md` handles that.
- Asking Claude to "remember" something from a prior session. It can't. Tell it where to read instead.

---

## Capturing context mid-session

When something surfaces that matters beyond this session, capture it immediately. The three lightweight options:

**ADR.** If it's a non-trivial architectural choice — a vendor, a framework, a schema change — ask Claude to draft a new ADR in `docs/decisions/`. Numbered, dated, append-only.

**Idea file.** If it's a thought that isn't scoped for now but shouldn't be lost, drop it in `docs/ideas/` as a short markdown file. Messy is fine. This is the parking lot.

**Roadmap edit.** If it's a milestone shift — dates, ordering, scope — update `docs/roadmap.md` directly.

The rule of thumb: if the thought would be missing context in a new session tomorrow, write it down now.

---

## Session rhythm

A healthy session has four beats:

1. **Confirm the goal.** Claude should (and usually does) confirm what you're trying to accomplish before diving in. If it doesn't, you can force the check with "Before writing anything, tell me what you think we're doing."
2. **Do the work.** Claude writes, you review in GitHub Desktop, you commit.
3. **Summarize what changed.** At natural pause points, ask: "Summarize what we changed in this session and what's left." This doubles as a checkpoint you can paste into the next session if you continue later.
4. **Decide what's next.** Explicit next-step pointer, ideally something that can be done in ~an hour of focused time.

If a session is going to run past a natural pause, consider asking Claude to update the roadmap with where you left off before stopping. That's the handoff note to your future self.

---

## Git workflow

Claude edits files using the file tools. Jon handles all git operations through GitHub Desktop. Claude does not run `git` commands in the sandbox — this caused a `.git/index.lock` collision early on and we've committed to not repeating it.

Branch-per-change is the norm:
- New branch per concern (`feat/cost-tracking`, `feat/working-with-claude`)
- Commit with a Conventional Commit message (`feat:`, `fix:`, `docs:`, `chore:`, etc.)
- Push, open PR, wait for CI green, merge
- Branch protection on `main` enforces PR + green CI; admin bypass is allowed for emergencies

Small PRs > big PRs. If two changes are unrelated, they're separate branches.

---

## Delegating to subagents

Claude can spawn subagents for focused tasks (`Agent` tool). Reach for this when:

- The task is well-scoped and read-heavy (e.g., "audit every dbt model for missing tests and produce a punch list").
- You want an independent second opinion (e.g., "review this ADR for gaps").
- The work would blow up the main session's context window.

Don't bother for quick edits or single-file reads. The overhead isn't worth it.

When Claude proposes a subagent, skim the prompt it's about to send. Bad prompts produce shallow, generic work. A good subagent prompt names specific files, specific questions, and a specific deliverable format.

---

## Drift correction

Signs a session has drifted:
- Responses are getting longer and less specific.
- Claude is hedging more, asking more clarifying questions, or restating context you already established.
- Answers are contradicting decisions from earlier in the same session.
- You've lost track of what's been committed vs. what's still staged.

Corrective moves (pick one):
- "Pause. Summarize what we've changed so far and what's still open."
- "Reread `CLAUDE.md` and tell me which principles we're currently violating, if any."
- Start a new session with a crisp opener and a link to the summary from the drifted one.

Starting over feels expensive but usually isn't. A fresh session with good inputs produces better output than a tired session pushing through fog.

---

## Quick reference

**Session opener template:**
> Working on [milestone/task]. Goal: [one sentence]. Read [specific doc(s)] first, then confirm with me before writing anything.

**End-of-session checkpoint:**
> Summarize what we changed, what's committed vs. staged, and what the next natural step is. If any decisions came up that should be captured, flag them.

**Drift correction:**
> Pause. Reread `CLAUDE.md` and the current roadmap. Summarize what we're actually trying to do right now.

**Capturing a stray thought:**
> That's out of scope for today. Drop a short file in `docs/ideas/` so we don't lose it.

**Second opinion:**
> Before we implement this, spawn a subagent to review the plan independently. I want a gut check on [specific concern].

---

## Responsibilities at a glance

**Claude**
- Reads `CLAUDE.md`, `docs/roadmap.md`, and relevant ADRs at the start of every session.
- Edits files via the file tools.
- Drafts ADRs, idea files, and roadmap updates on request.
- Flags cost implications, leakage risk, and sport-agnostic schema violations proactively.
- Does not run `git` commands.

**Jon**
- Sets the session goal up front.
- Handles all git operations in GitHub Desktop.
- Reviews diffs before committing.
- Decides when to start a new session vs. continue.
- Keeps the docs current — or asks Claude to.

---

## Maintenance

This file is a working agreement, not scripture. When something about the Jon↔Claude workflow changes — new tool, new convention, new failure mode worth documenting — update this file in a small PR. Keep it short; bloat defeats the purpose.
