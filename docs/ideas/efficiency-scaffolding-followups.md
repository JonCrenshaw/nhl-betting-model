# Efficiency / scaffolding follow-ups

Parked ideas for improving the agentic workflow on PuckBunny. None of these are scoped for current work. The milestone-close efficiency review (see `docs/efficiency.md`) walks this list and decides whether any are now justified.

If an item graduates into active work, move its content into the relevant doc and delete the entry here. If an item has been parked for several reviews without anyone reaching for it, delete it — indefinite parking is a smell.

---

## Repo map (`docs/repo-map.md`)

One-page directory tour: one sentence per top-level folder. Saves Claude from globbing/grepping its way to a mental model on every fresh session.

**Promote when:** the repo grows past ~10 top-level directories, or sessions are visibly spending tool calls on directory exploration.

**Owner moment if promoted:** PR template checkbox when a new top-level folder lands.

---

## Recipe docs in `docs/how-to/`

Short cookbook entries: "how to add a new ingestion endpoint," "how to add a new dbt model," "how to wire a new feature into the gold layer." Each names the files to touch in order, conventions to follow, and the test that proves it works.

**Promote when:** a pattern has been done two or three times. Each recipe should follow at least two prior examples in the codebase, never one.

---

## Additional `.claude/commands/` slash commands

Commands live at `.claude/commands/`. Current set: `/start`, `/wrap`, `/new-adr`, `/leakage-check`, `/calibration-check`, `/efficiency-review` (promoted M2 close). Queued candidates:

- `/cost-check` — audits operational cost vs. the ~$50/month V1 ceiling
- `/dbt-test-coverage` — punch list of dbt models missing tests
- `/adr-review` — second-opinion read of an ADR before it's accepted
- `/clv-snapshot` — once odds and picks pipelines exist, dump current CLV stats

**Promote when:** Jon notices himself typing similar prose into multiple sessions, or when one of the workflows above becomes a regular cadence.

---

## Anti-pattern / lessons-learned log (now `docs/gotchas.md`)

Partially landed. `docs/gotchas.md` exists as of the initial scaffolding pass and currently holds the cross-mount file safety rules and the dev container guidance. The broader idea is to grow it into a more general "we tried this, it broke, here's the rule now" log as more incidents accumulate.

**Promote (= grow) when:** a non-trivial debugging session produces a rule worth preserving. Append it to `docs/gotchas.md` with date and short context. The hardest part is remembering to do this in the moment — `/wrap` prompts for it.

---

## Subagent prompt templates (`docs/subagent-prompts.md`)

Pre-written prompts for recurring delegation patterns: "review this ADR for gaps," "audit dbt models for missing tests," "find time-leakage in feature code under `src/`."

**Promote when:** Jon has spawned subagents for the same kind of task at least twice and noticed the prompt would be better if pre-written.

---

## Machine-readable schema snapshot

A `docs/architecture/silver-schema.md` (or generated `dbt docs` artifact) so Claude doesn't have to introspect tables to plan a feature.

**Promote when:** the silver layer is built (M3) and feature work (M5+) starts referencing it. Strongly prefer generation from `dbt docs` over hand-writing.

---

## Pre-commit hooks as cheap verification

Specific hooks worth adding to the existing pre-commit config:

- A leakage-detection check (custom script that flags features joining on as-of-today dimensions without a temporal filter).
- A "no `print` statement in `src/`" check that enforces the structured-logging rule from `CLAUDE.md`.

**Promote when:** feature engineering code (M5+) starts landing, or Jon catches a leakage bug in review that a hook would have caught.

---

## dbt model YAML descriptions as living docs

Every dbt model gets a description in YAML (already a `CLAUDE.md` rule). The follow-up: enforce description presence in a CI check, and use `dbt docs generate` output as Claude's primary reference for schema during feature work.

**Promote when:** dbt model count exceeds ~10 and Claude is being asked to plan against the warehouse during sessions.

---

## Connectors / plugins

Worth checking the registry the next time we hit a "I wish Claude could just look at X" moment. Likely first candidates:

- GitHub MCP — read PR conversations and CI failures without paste-the-output round-trips.
- DuckDB or R2 connector — once the warehouse exists, query the silver layer during planning instead of guessing at row counts.

**Promote when:** the friction is concrete and recurring.

---

## Artifacts for things we'll re-check

Live, persisted artifacts (the kind that re-fetch data on each open) that replace recurring asks. Likely candidates:

- Backtest / CLV monitoring dashboard (post-M11)
- Pipeline health page (post-M10)
- Pick log / transparency view (Phase 2)

**Promote when:** a question is being asked of Claude on a regular cadence and the underlying data changes between asks.

---

## Scheduled tasks for recurring audits

Once the pipeline is live, scheduled tasks for:

- Weekly cost audit vs. the $50/month ceiling
- Weekly CLV summary
- Periodic calibration check on the live model

**Promote when:** the daily pipeline (M10) is running and any of the above is something Jon is doing manually.

---

## Maintenance

Reviewed at every milestone close per the cadence in `docs/efficiency.md`. Items that have been parked for several reviews without justification should be deleted, not kept indefinitely.
