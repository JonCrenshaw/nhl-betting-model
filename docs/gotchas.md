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

## Maintenance

Append new entries below as incidents produce rules worth preserving. Each entry should:

1. State the rule up front.
2. Explain the war story briefly enough to make the rule stick.
3. Date the entry if the rule is tied to a specific tool version or vendor behavior that may change.

Resolved gotchas (rule no longer needed because the underlying cause was fixed upstream) can be deleted. Don't archive them — the git history is the archive.
