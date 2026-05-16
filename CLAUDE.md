# CLAUDE.md

Working agreements for Claude Code sessions on this repository. Claude should read this file at the start of every session.

---

## Project context

**Product name.** PuckBunny. The repo is `nhl-betting-model` (sport-specific) while the product-facing name is PuckBunny. The name is hockey-specific — multi-sport expansion in Phase 3 will force a branding discussion (parent brand, rename, or per-sport sub-brands). Flag this when product/marketing decisions come up.

**Goal.** Build a predictive model that identifies +EV bets by comparing model-implied probabilities with sportsbook odds. Phase 1 scope is the NHL. The architecture is sport-agnostic from the silver layer up, so MLB, NBA, NFL, and European soccer can be added in Phase 3 without a schema rewrite.

**Phases.**
1. **Proof of concept.** Daily pipeline, calibrated models, backtested, paper-traded, then live-bet. V1 success = get limited on a major sportsbook.
2. **Productionalize.** Subscription product with web UI, auth, billing, and a public-facing credibility story (live CLV tracker).
3. **Multi-sport expansion** (future). MLB, NFL, NBA, European soccer leagues. Schema must support this without a rewrite.

**Owner.** Jon Crenshaw. Time budget ~10 hrs/week. Jon is strong in SQL, competent in Python/R, novice in web/React.

---

## Session startup checklist

At the start of any substantive session, Claude should:

1. Read this file.
2. Read `docs/now.md` for current state of work — active branch/PR, what's in flight, blockers, and the next concrete step.
3. Read `docs/roadmap.md` to identify the current phase and active milestone.
4. Skim `docs/decisions/` for prior architectural decisions relevant to the task at hand.
5. Skim `docs/ideas/` for parked ideas related to the task.
6. Confirm with Jon what the specific goal of this session is before writing code.

The `/start` slash command in `.claude/commands/` runs this checklist programmatically.

---

## Session close checklist

At the end of any substantive session, Claude should:

1. **Update `docs/now.md`** to reflect current state — active branch/PR, currently-in-flight items, last session summary (replaced, not appended), blocked items with reasons, and the next concrete step. This update happens every session, without being asked. Replace, don't append; git history is the log, `now.md` is the snapshot.
2. Capture anything that should outlive the session: a new ADR (`/new-adr`), an idea file in `docs/ideas/`, a roadmap edit, or a `docs/gotchas.md` entry, as appropriate.
3. If a milestone just closed, remind Jon of the milestone-close review cadence in `docs/efficiency.md` and offer to run it.
4. Recommend a Conventional Commit message and branch name if there are uncommitted changes worth committing. Don't run `git` — Jon handles git operations in GitHub Desktop.

The `/wrap` slash command in `.claude/commands/` runs this checklist programmatically.

---

## Development principles

1. **Scalability over shortcuts.** Every V1 choice must support V2 scale without a rewrite. When a cheap-now choice paints us into a corner, flag it and propose the scalable alternative with costs.
2. **Cost-consciousness.** V1 operational budget ceiling is ~$50/month. Flag anything that threatens it.
3. **Sport-agnostic data model.** Silver and gold layers of the warehouse must not encode NHL-specific assumptions. Sport goes in a column, not a schema.
4. **Calibrated probabilities are required.** Raw classifier outputs are not probabilities. Apply Platt scaling, isotonic regression, or Bayesian methods before any bet selection logic consumes them.
5. **Closing Line Value is the primary measure of edge.** ROI is a secondary, noisier signal. Every pick must be logged with closing line captured as close to game time as possible.
6. **Reproducibility.** Any result must be reproducible from committed code, pinned dependencies, and versioned data snapshots.
7. **Defensive defaults.** Pipelines should fail loudly and safely. No silent fallbacks, no swallowed exceptions, no default bet sizes.

---

## Coding standards

### Python
- Python 3.12.
- Package manager: `uv`.
- Formatter/linter: `ruff format`, `ruff check` (configured in `pyproject.toml`).
- Type checker: `mypy` in strict mode for new modules.
- Tests: `pytest`. Target 80%+ coverage for modeling, scoring, bet-selection logic. Lower acceptable for one-off scripts.
- Structured logging: `structlog` or stdlib `logging` with JSON output. No `print` statements in production code.

### SQL / dbt
- All warehouse transforms go through dbt.
- Style: `sqlfluff` with the dbt dialect.
- Naming conventions:
  - `stg_<source>__<entity>` — thin cleaning layer over raw
  - `int_<entity>__<purpose>` — intermediate transformations
  - `fct_<entity>` — fact tables
  - `dim_<entity>` — dimension tables
  - `mart_<domain>__<entity>` — consumer-facing marts
- Every dbt model has a description in YAML. Fact tables have unique+not-null tests on primary keys.

### R
- R is acceptable for exploratory modeling and one-off analysis, not pipeline code.
- If an R prototype is promoted to production, port it to Python first.

### Frontend (V2)
- Next.js + TypeScript in strict mode.
- ESLint with `next/core-web-vitals` + `@typescript-eslint/recommended`. Prettier. No disabling rules without comment.
- Playwright for E2E. Preview deployments enabled on every PR.
- Because Jon is a React novice, every frontend PR gets Claude-generated review notes highlighting anti-patterns, accessibility issues, and state-management concerns.

### Commit messages
- Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- Reference ADR numbers where relevant, e.g. `feat(warehouse): adopt DuckDB (ADR-0001)`.
- **Claude should proactively recommend a branch name and a commit message body whenever a session reaches a commit-worthy stopping point** — a milestone PR with passing tests, a logical chunk of refactor that stands on its own, a finished documentation pass, etc. Don't wait to be asked. Branch naming for milestone PRs follows `feat/m<N>-pr-<letter>-<short-slug>` (e.g. `feat/m2-pr-e-schedule`); other branches use the conventional-commit type as the prefix (`fix/...`, `docs/...`, `refactor/...`). The commit body should summarize *what* landed and *why* — long bodies are fine when the change has tradeoffs or non-obvious choices worth recording for future archeology.

---

## Testing requirements

- New features require tests.
- Any model-training code must include:
  - A reproducibility test (same seed → same output).
  - A calibration check on a held-out sample.
  - Time-based split validation — never random splits for time-series data. No feature may use information unavailable at the target timestamp.
- Pipeline code must include a smoke test that runs on a small fixture.
- Backtests must honor the "no peeking" rule; Claude should actively hunt for leakage in every new feature.

---

## Do / Don't

**Do**
- Track Closing Line Value on every pick.
- Version snapshots of odds at open, key movements, and close.
- Log model uncertainty, not just point predictions.
- Document non-obvious modeling choices in an ADR or inline comment linking to one.
- Keep feature engineering in the warehouse (dbt) where possible. Only use Python for features that genuinely need it (e.g., NLP, external APIs).
- Surface cost implications before adopting new services.
- Treat Jon as a reviewer, not a validator. Explain what the code is doing and why, especially in React and anywhere Python uses advanced patterns.

**Don't**
- Hardcode bet sizes. Bet sizing is its own module and is always configurable.
- Commit API keys, raw scraped data, or any odds snapshot that includes user-identifying info.
- Trust single-season backtests. Variance on ~1,300 games per NHL season is enormous.
- Peek at future data in feature construction (including subtle leakage through joins on as-of-today dimensions).
- Build sport-specific assumptions into gold-layer models. `team_id`, `player_id`, `market_id`, `sport_id` are the universal keys.
- Introduce a new tool, vendor, or framework without writing an ADR.

---

## Cross-mount file safety and dev container guidance

Both live in `docs/gotchas.md`:

- **Cross-mount file safety** — rules for the Windows + Linux-devcontainer setup, including the `.git/config` truncation hazard, the read-then-write round-trip ban, and the recovery procedure for stale bash views.
- **Dev Container guidance** — when to cue Jon to switch into the devcontainer (production-shaped runtime work, reproducing CI failures, filesystem-semantics-sensitive work, first-run vendor validation, native-Linux-only tooling) and when not to nag. Default workflow is Windows-native.

Read `docs/gotchas.md` at the start of any session that might touch either area. The load-bearing one-liners:

- Use Windows-side file tools (Read/Write/Edit) for anything where file content authority matters.
- Use the Linux bash tool for command execution, not as a read-then-write pipeline for file contents.
- If a file appears different between the two views, trust the Windows side.

---

## Decision records (ADRs)

Any non-trivial architectural choice goes in `docs/decisions/` as a numbered file. Format is in [docs/decisions/README.md](./docs/decisions/README.md). ADRs are append-only: never delete, supersede with a new one.

Examples of things that require an ADR:
- Choosing a warehouse, orchestration tool, or modeling framework
- Adopting a new external data source or API
- Changing the silver-layer schema
- Adopting or dropping a subscription vendor

Examples of things that **don't** need an ADR:
- Day-to-day code changes
- Adding a new dbt model within existing conventions
- Bug fixes

---

## Ideas folder

`docs/ideas/` is a parking lot. When a thought comes up mid-conversation that isn't scoped for current work, drop it there as a short markdown file. Files can be messy. When an idea graduates into active work, move its content into the relevant doc or ADR and delete the idea file.

---

## Subagents

Three cases warrant a subagent in this project:

1. **Bronze/staging schema discovery** — if you need to understand what fields a `response_json` endpoint actually contains before writing a staging or intermediate model, use `subagent_type=Explore`. Keeps 5–10 file reads out of the main context.
2. **Audit tasks** — `/leakage-check`, `/calibration-check`, or dbt model test-coverage gaps. Delegate to a general-purpose subagent; results are large and read-only.
3. **Genuinely parallel independent models** — when two or more dbt models share no dependency and the session benefits from parallel build, use worktree isolation.

Do not spawn a subagent for targeted lookups (Glob/Grep is faster), or for code-writing tasks where you'd need to verify the output anyway.

Pre-written prompts for recurring delegation patterns live in `docs/ideas/efficiency-scaffolding-followups.md` (promote when a pattern has been used twice).

---

## Efficiency reviews

`docs/efficiency.md` defines the principles and review cadence for keeping the agentic workflow lean. The review runs at every milestone close — `/wrap` prompts for it when a milestone has just closed. Parked ideas for future scaffolding live in `docs/ideas/efficiency-scaffolding-followups.md`.

The core principle: optimize for **time-to-correct-action in a fresh session**. Every doc and every piece of scaffolding either reduces that time or increases it. Docs that go stale are worse than missing — every doc that requires manual maintenance needs an obvious owner moment.

---

## Folder structure

```
nhl-betting-model/
├── CLAUDE.md                      # This file
├── README.md                      # Project overview
├── docs/
│   ├── now.md                     # Current state of work — updated every session
│   ├── roadmap.md                 # Phased milestones
│   ├── efficiency.md              # Agentic-efficiency principles & review cadence
│   ├── gotchas.md                 # Lessons learned (cross-mount, devcontainer, etc.)
│   ├── working-with-claude.md     # How Jon and Claude collaborate (companion to this file)
│   ├── development.md             # Dev environment notes
│   ├── data-sources.md            # Catalog of external data sources
│   ├── glossary.md                # Domain terms
│   ├── architecture/
│   │   └── data-warehouse.md      # Warehouse design
│   ├── costs/                     # Cost tracking (budget, expenses.csv)
│   ├── milestones/                # Per-milestone planning docs
│   ├── decisions/                 # ADRs (append-only)
│   └── ideas/                     # Parking lot
├── src/                           # Python source
├── dbt/                           # dbt project
├── tests/                         # Test suite
├── .claude/
│   └── commands/                  # Slash commands (/start, /wrap, /new-adr, /leakage-check, /calibration-check)
└── pyproject.toml                 # Python project config
```

---

## Responsible gambling

This project exists because Jon chooses to engage with sports betting. Any user-facing surface (Phase 2) must include:
- Clear probabilistic framing (not "locks" or guarantees).
- Responsible-gambling resources linked from every page.
- No marketing copy that promises profits or targets vulnerable users.

Claude should push back if product or marketing decisions drift toward predatory framing.
