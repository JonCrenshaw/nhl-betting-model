# Gotchas

Lessons learned the hard way. "We tried this, it broke, here's the rule now."

This file exists so painful debugging sessions become permanent guardrails rather than rediscovered next session. Append new entries as incidents accumulate. Keep each entry short, with the rule stated up front and the war story below.

`CLAUDE.md` references this file rather than embedding these sections directly, to keep the always-loaded working agreements lean.

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

## Worktree vs. main repo — write to the right path (Claude)

When a Claude session runs in a worktree, the Read/Write/Edit tools take absolute paths and don't enforce which working tree the file belongs to. It is easy for Claude to write a file to the **main repo path** (`D:\Git\PuckBunny\nhl-betting-model\...`) when it meant to write to the **worktree path** (`...\.claude\worktrees\<name>\...`). The change then shows up on `main` in GitHub Desktop as a stray edit instead of on the PR branch, which is confusing and easy to miss.

Rules:

- When working in a worktree, **always write to the worktree's absolute path**, not the main repo's. Double-check the path prefix on every `Write` / `Edit` call.
- If GHD shows changes on `main` that weren't intentional, the most common cause is a stray write to the main repo. Revert with `git checkout -- <file>` and `git clean -f <file>` for untracked stragglers, then re-do the change in the worktree.
- Tools that take `--project-dir` / `--profiles-dir` / similar (dbt, uv) act on the directory you're in or the path you pass — not on whichever worktree happens to be active in the editor. Be explicit.

This came up shipping M3 PR-A (May 2026): `motherduck.md` and `.env.example` were written to `main` first, then re-written to the worktree, leaving duplicates on `main` that had to be reverted before the PR could open cleanly.

---

## Don't store credentials in committed files — even "just for a minute" (Claude + Jon)

Secrets go in `.env` (gitignored) or the OS environment. Never in a tracked or about-to-be-tracked file, even temporarily. The fact that a file is currently untracked is not protection — one stray `git add .` and it's in history.

Rule: if a credential needs to be persisted, it goes to `.env` directly. Runbooks reference *where* the credential goes by variable name (e.g., `MOTHERDUCK_TOKEN`), never the value.

If a credential does land in a committed-or-stageable file, rotate it immediately — assume it's compromised the moment it touches a file under the repo root.

This came up provisioning MotherDuck (May 2026): the raw JWT was pasted into `docs/infrastructure/motherduck.md`. It was caught untracked and rotated before any commit, but the close call drove the rule.

---

## dbt in a worktree — setup checklist (Claude + Jon)

Gitignored files don't transfer to a new worktree. Every worktree needs its own copies of:

1. **`dbt/profiles.yml`** — copy from `dbt/profiles.yml.example` and fill in values. Without it, `dbt debug` fails with "Profile puckbunny not found".
2. **`data/` directory** — DuckDB can't create its own parent directories. `New-Item -ItemType Directory -Path dbt/data -Force` before any `dbt run --target dev`.
3. **Always pass `--profiles-dir dbt`** — dbt defaults to `~/.dbt/` which may not exist or may point to a different project.

**Prod-specific: seed before you test FK relationships.**
`dim_league` and `dim_sport` are seeds, not models. `dbt build --select +dim_team` doesn't include seeds in scope. Run `dbt seed --target prod` once per fresh MotherDuck database before any `dbt test` that uses a `relationships` test pointing at those tables — otherwise you get `Table with name dim_league does not exist!`.

**R2 env vars: two spellings, two callers.**
`.env` needs both:
- `R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com` — used by boto3 (Python ingestion), which requires a full URL with scheme.
- `R2_ENDPOINT=<account-id>.r2.cloudflarestorage.com` — used by DuckDB's `s3_endpoint` setting, which prepends its own `https://` and breaks if given a full URL. If `R2_ENDPOINT` is missing, DuckDB silently falls back to `s3.auto.amazonaws.com` (AWS default) and every `READ_PARQUET` call 404s with a misleading hostname error.

This came up shipping M3 PR-C (May 2026).

---

## filter_ingestible only checks game_state, not game_type

`filter_ingestible` in `src/puckbunny/ingestion/nhl/schedule.py` passes any game in state `{FINAL, OFF}` — it does **not** filter on `game_type`. All-Star games, the 4 Nations Face-Off, and any future non-competitive event will land in R2 if they finish with state FINAL.

Current defense: `stg_nhl__landing`, `stg_nhl__boxscore`, and `stg_nhl__play_by_play` each have `WHERE game_type IN (2, 3)` in the source CTE, so non-competitive games are excluded from the silver layer.

Follow-up fix needed: add `game_type IN (2, 3)` to `filter_ingestible` so bronze stays clean too. Until then, non-competitive game Parquet files accumulate in R2 (wasteful but harmless given current bronze read cost).

This came up when the 2024-25 M2 backfill pulled All-Star Weekend and 4 Nations games into R2, causing `accepted_values` test failures on `stg_nhl__landing.game_type`.

---

## sqlfluff ST06 false positive on UNNEST-derived CTEs (Claude)

**Rule:** When an intermediate dbt model unnests a JSON array, add `-- noqa: ST06` to the outer SELECT. Do not spend time restructuring — it won't help.

**Why:** sqlfluff's DuckDB dialect cannot determine column origin through `CROSS JOIN UNNEST(col::JSON [])`. As a result it misclassifies a genuine column reference (`game_id`) as a calculated expression and fires ST06 ("simple targets before calculations") even when the column order is correct. Five structural variations were tried (UNNEST-in-SELECT, two-CTE, FROM-clause CROSS JOIN UNNEST, wrapped/unwrapped function calls, subqueries) and all produced the same false positive at the outer SELECT.

**Fix pattern:**
```sql
WITH plays_unnested AS (
  SELECT
    p.game_id,
    t.play
  FROM {{ ref('...') }} AS p
  CROSS JOIN UNNEST(p.col::JSON []) AS t (play)
)

-- noqa: disable=ST06 — UNNEST-derived CTE; game_id is a column ref but
-- the linter cannot determine its origin through the CROSS JOIN UNNEST.
SELECT  -- noqa: ST06
  game_id,
  JSON_EXTRACT_STRING(play, '$.field') AS field,
  ...
FROM plays_unnested
```

First surfaced in `int_nhl__game_events.sql` (M3 PR-E, May 2026).

---

## Maintenance

Append new entries below as incidents produce rules worth preserving. Each entry should:

1. State the rule up front.
2. Explain the war story briefly enough to make the rule stick.
3. Date the entry if the rule is tied to a specific tool version or vendor behavior that may change.

Resolved gotchas (rule no longer needed because the underlying cause was fixed upstream) can be deleted. Don't archive them — the git history is the archive.
