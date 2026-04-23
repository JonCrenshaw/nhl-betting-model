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
2. Read `docs/roadmap.md` to identify the current phase and active milestone.
3. Skim `docs/decisions/` for prior architectural decisions relevant to the task at hand.
4. Skim `docs/ideas/` for parked ideas related to the task.
5. Confirm with Jon what the specific goal of this session is before writing code.

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

## Folder structure

```
nhl-betting-model/
├── CLAUDE.md                      # This file
├── README.md                      # Project overview
├── docs/
│   ├── roadmap.md                 # Phased milestones
│   ├── data-sources.md            # Catalog of external data sources
│   ├── glossary.md                # Domain terms
│   ├── architecture/
│   │   └── data-warehouse.md      # Warehouse design
│   ├── costs/                     # Cost tracking (budget, expenses.csv)
│   ├── decisions/                 # ADRs
│   └── ideas/                     # Parking lot
├── src/                           # Python source (created in M1)
├── dbt/                           # dbt project (created in M1)
├── tests/                         # Test suite (created in M1)
├── .claude/                       # Claude Code config
│   ├── commands/                  # Slash commands (later)
│   └── skills/                    # Custom skills (later)
└── pyproject.toml                 # Python project config (created in M1)
```

---

## Responsible gambling

This project exists because Jon chooses to engage with sports betting. Any user-facing surface (Phase 2) must include:
- Clear probabilistic framing (not "locks" or guarantees).
- Responsible-gambling resources linked from every page.
- No marketing copy that promises profits or targets vulnerable users.

Claude should push back if product or marketing decisions drift toward predatory framing.
