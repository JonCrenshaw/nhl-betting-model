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

## Cross-mount file safety (Claude)

Jon works on Windows; an optional Linux devcontainer bind-mounts the workspace. Claude can see the repo from both sides: the Read/Write/Edit file tools talk to the Windows filesystem directly, while the bash tool runs inside the Linux container and reads the same files through a bind mount.

Known hazard: the Linux side can serve **truncated** views of a file when the Windows side hasn't finished flushing — the tail of the file is silently missing, with no error from either OS. If Claude reads a file through the Linux side and writes that view back, it can overwrite the full Windows file with a fragment. In one session this corrupted `.git/config` (16 of 47 lines), which broke every git tool on the repo — CLI, GitHub Desktop, VS Code Source Control, pre-commit — until the file was manually reconstructed.

Rules:
- Use Windows-side file tools (Read/Write/Edit) for anything where file content authority matters. They are the source of truth.
- Use the Linux bash tool for command execution (running scripts, git, tests, dbt, uv) — not as a read-then-write pipeline for file contents.
- Never round-trip a file through the Linux side to "preserve" or "back up" its state. If a backup is needed, copy it via a Windows-side tool.
- If a file appears different between the two views, trust the Windows side.

### Recovery procedure when bash gets a stale view

A file that Windows already has correctly (verified via Read) may still appear truncated, NUL-padded, or BOM-prefixed when read from bash. Symptoms: `cat` returns fewer bytes than `stat -c %s`; ruff / mypy / uv parse errors that don't reproduce on Windows; `git status` reports a wrong tree because `.git/config` reads as a fragment.

Workaround that has worked: from the Linux side, rename the file to a sibling and back —

```bash
mv path/to/file path/to/file.tmp && mv path/to/file.tmp path/to/file
```

This forces the FUSE bind mount to reissue inode metadata and usually causes the Linux view to converge on the Windows-side bytes. Verify after by re-reading and comparing length to the Windows-side `Read` tool.

This is a recovery move, not a substitute for the rules above. Specifically:

- Only use it on files where the Windows side is known to be correct. The mv goes through the Linux side, so if Linux already has a corrupted view it can write that view back to Windows — same hazard as the original truncation. Read the Windows-side file first to confirm authority.
- Never run it on `.git/config`, `.git/index`, or anything else inside `.git/`. We've seen this combination create a Linux-only "ghost" view of `.git/config` (e.g., 512 bytes with a UTF-8 BOM) that no further mv can dislodge, and a `.git/index.lock` that the FUSE mount won't let bash delete (`Operation not permitted`). When bash-side git is broken, hand off to the Windows shell — don't try to fix `.git` from Linux.
- Don't use it to "rescue" a file you just wrote from bash. That's the round-trip the rules above forbid.

---

## Dev Container guidance (Claude)

The repo ships a Dev Container (ADR-0002), but Jon's default workflow is Windows-native — `uv`, `ruff`, `pytest`, and `dbt` all run directly. That's fine for everyday Python/SQL/docs work, and Claude should not add devcontainer friction by default.

Claude *should* proactively cue Jon to switch into the devcontainer ("Dev Containers: Reopen in Container" in VS Code) when the next step has meaningful Windows-vs-Linux divergence risk. Triggers:

- **Production-shaped runtime work.** Anything Dagster (M10+), dbt against the cloud warehouse, integration tests that hit R2 from a Linux-shaped client, or anything else that simulates the deployed environment.
- **Reproducing a CI failure.** CI runs on Ubuntu. If local tests are green but CI is red, the devcontainer is the shortest path to a reproduction.
- **Filesystem-semantics-sensitive work.** Symlinks, file locking, case-sensitive path resolution, anything where NTFS vs ext4 might silently differ.
- **First-run validation of a new vendor or tool.** Verify on Linux before locking in via ADR.
- **Anything that requires native Linux tooling** that doesn't have a clean Windows equivalent.

The cue should be one line — *"worth reopening in the devcontainer for this — production-shaped environment matters here"* — and Claude should let Jon decide. Don't silently assume he's already inside one. Once Jon confirms he's switched, Claude can proceed; until then, hold off on work that depends on the Linux environment.

When the work *doesn't* match a trigger, Claude should not nag. The default is Windows-native.

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
