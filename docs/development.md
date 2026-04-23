# Development

Setup, workflow, and commands for day-to-day work on the repo. For architectural
decisions see [decisions/](./decisions/); for the phased plan see [roadmap.md](./roadmap.md);
for how Jon and Claude collaborate see [working-with-claude.md](./working-with-claude.md).

---

## First-time setup

From the repo root, in any shell (PowerShell, bash, zsh, the VS Code integrated terminal):

```
uv sync
uv run pre-commit install
```

- `uv sync` creates `.venv/` and installs every dependency — runtime (none yet) plus the
  `dev` group — at the exact versions pinned in `uv.lock`. Re-run any time `uv.lock`
  changes on `main`.
- `uv run pre-commit install` wires the pre-commit framework into `.git/hooks/pre-commit`
  so the hooks configured in `.pre-commit-config.yaml` run on every commit.

If you don't have `uv` yet, install it from PowerShell:

```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

(or the Bash/curl variant on macOS/Linux — see [uv's install docs](https://docs.astral.sh/uv/getting-started/installation/)).

---

## Daily workflow

One branch per change. Loop:

1. Create a branch off `main`. Conventional prefixes: `feat/…`, `fix/…`, `chore/…`, `docs/…`.
2. Make changes. Commits pass through the pre-commit hooks automatically.
3. Push, open a PR. CI runs ruff + a hygiene job (gitleaks warn-only, large-file check)
   and activates pytest / sqlfluff conditionally once those surfaces exist.
4. Merge once CI is green. Branch protection on `main` enforces PR + green CI.

Small PRs > big PRs. If two changes are logically independent, split them.

### Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) format. The prefixes we use:

- `feat:` — new user-facing capability
- `fix:` — bug fix
- `chore:` — tooling, infrastructure, repo hygiene
- `docs:` — documentation-only changes
- `refactor:` — code restructuring with no behavior change
- `test:` — test additions or changes only

Reference ADR numbers when a commit implements a decision:

```
feat(warehouse): adopt DuckDB (ADR-0001)
```

---

## `uv` commands

Day-to-day commands and what they do:

- `uv sync` — install `uv.lock` into `.venv`, removing anything not in the lock.
  Deterministic and fast; the canonical "get my environment right" command.
- `uv add PKG` — add a runtime dependency. Edits `pyproject.toml` and `uv.lock`;
  commit both in the same commit.
- `uv add --group dev PKG` — add a dev-only dependency (linters, test tooling, etc.).
- `uv remove PKG` / `uv remove --group dev PKG` — the inverse.
- `uv lock` — regenerate `uv.lock` without touching `.venv`. Useful to see what a
  `pyproject.toml` change would resolve to before committing to an install.
- `uv lock --upgrade` — bump every dep to its latest compatible version and rewrite
  `uv.lock`. Review the diff carefully before committing.
- `uv run CMD` — run `CMD` inside `.venv` without activating the venv first.
  Examples: `uv run pytest`, `uv run ruff check .`, `uv run pre-commit run --all-files`.

---

## dbt

The dbt project lives in `dbt/`. Local runs use DuckDB; production uses
MotherDuck. Both via the `dbt-duckdb` adapter. See
[ADR-0001](./decisions/0001-warehouse-stack.md) for the warehouse rationale
and `dbt/profiles.yml.example` for the connection shape.

**First-time dbt setup**

1. Copy `dbt/profiles.yml.example` to `dbt/profiles.yml` (or `~/.dbt/profiles.yml`).
   The project-local file is gitignored, so credentials stay local.
2. Fill in the `dev` target's file path if you want it somewhere other than
   `./data/puckbunny.duckdb`.
3. For the `prod` target and for reading bronze from R2, set the relevant
   env vars: `MOTHERDUCK_TOKEN`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY`.

**Running dbt**

All commands run from the `dbt/` directory (or pass `--project-dir dbt`):

- `uv run dbt debug` — verify the connection to your configured target.
- `uv run dbt parse` — parse the project without executing models. Fast sanity
  check after editing models or macros.
- `uv run dbt run` — materialize all models against the current target.
- `uv run dbt run -s stg_nhl_api__games` — run a single model by name.
- `uv run dbt test` — run all configured tests.
- `uv run dbt build` — parse + run + test in one shot. The daily pipeline
  will wrap this.
- `uv run dbt clean` — delete `target/` and `dbt_packages/`.

**sqlfluff**

- `uv run sqlfluff lint dbt/` — lint every SQL file under `dbt/` using the
  config in `.sqlfluff`. Mirrors the pre-commit hook and the CI sql job.
- `uv run sqlfluff fix dbt/` — auto-fix lint violations where possible.
  Review the diff before committing — sqlfluff's rewrites are usually
  correct but not always what you want stylistically.

**Naming conventions** are enforced by code review, not tooling:

- `stg_<source>__<entity>` — staging layer
- `int_<entity>__<purpose>` — intermediate
- `fct_<entity>` / `dim_<entity>` / `mart_<domain>__<entity>` — marts

Every model lives alongside a `schema.yml` describing columns and declaring
at least a `unique` + `not_null` pair on the primary key of fact tables.

## `pre-commit` commands

- `uv run pre-commit run --all-files` — run every configured hook against the entire
  repo. Useful after pulling a big change or after editing `.pre-commit-config.yaml`.
  Hooks only run against staged files in normal commits; this forces a full sweep.
- `uv run pre-commit autoupdate` — bump every hook's `rev:` pin to its latest tag.
  Commit the resulting `.pre-commit-config.yaml` diff.
- `uv run pre-commit clean` — wipe the local hook cache at `~/.cache/pre-commit/`.
  Use when a hook install is stuck with a corrupted download (see gotchas below).

---

## Dependency management

**Golden rule:** `pyproject.toml` and `uv.lock` are committed together. A PR that
changes one without the other is wrong.

**Adding a runtime dep**
1. `uv add PKG`
2. Verify the `uv.lock` diff is what you expect — no surprise transitive pins,
   no suspicious packages.
3. Commit `pyproject.toml` + `uv.lock` in the same commit.

**Adding a dev dep**
Same workflow with `uv add --group dev PKG`.

**Upgrading**
`uv lock --upgrade` regenerates the lockfile with the newest compatible versions.
Read the diff. If the diff is large and spans unrelated packages, split: bump the
package you actually came to bump (`uv add PKG@latest`), then handle transitive
bumps in a separate PR so reviews stay sane.

**Never hand-edit `uv.lock`.** Regenerate it with a uv command.

---

## Known gotchas

### Gitleaks pre-commit hook is currently disabled
See [docs/ideas/gitleaks-local-hook.md](./ideas/gitleaks-local-hook.md). The official
hook downloads a Go SDK on first run and that download fails through some network
paths (middleboxes corrupt the SDK zip). CI's gitleaks job still runs on every PR,
so secret-scanning coverage is intact; what's missing is the pre-push local catch.
Follow-up PR to land a system-installed gitleaks or an equivalent is tracked in the
idea file.

### `BadZipFile` or `SSL: UNEXPECTED_EOF_WHILE_READING` from pre-commit
A mid-download network interruption can poison the pre-commit cache. Fix:

```
uv run pre-commit clean
uv run pre-commit run --all-files
```

If it keeps failing, the download is being interrupted by something on the network
path (corporate proxy, antivirus TLS inspection, VPN). Try a different network.

### `uv sync` seems to skip dev tools
Dev deps live in `[dependency-groups].dev` (PEP 735), which `uv sync` installs by
default. If they're not being installed, check that `pyproject.toml` still declares
the group correctly and that your `uv` is `0.4.27` or newer. The pre-PEP-735 form —
`[project.optional-dependencies].dev` — required `uv sync --all-extras` and we
explicitly migrated away from it.

### `dbt debug` fails with "Profile puckbunny not found"
You haven't created `dbt/profiles.yml` yet. Copy it from
`dbt/profiles.yml.example` and fill in values. The real file is gitignored.

### `Failed to build nhl-betting-model` on first sync
`[tool.uv] package = false` in `pyproject.toml` tells uv not to treat the project
as an installable package, because `src/` doesn't exist yet. If you see this
error, confirm the `[tool.uv]` block is still present. Remove it when `src/`
lands and we want editable installs of our own code.
