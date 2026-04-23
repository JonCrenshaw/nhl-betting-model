# Local gitleaks pre-commit hook

Parked in the pre-commit PR (PR 2 of M1 setup).

## Problem

The official `gitleaks-pre-commit` hook uses `language: golang`, which makes
pre-commit download the Go SDK from `go.dev/dl/` on first run, build the
gitleaks binary from source, and cache the result.

On Jon's Windows machine the Go SDK download fails consistently with either
`SSL: UNEXPECTED_EOF_WHILE_READING` or `BadZipFile`. Stack trace points to
`pre_commit/languages/golang.py:_install_go -> _open_archive`. Most likely
cause: a middlebox (corporate proxy, antivirus TLS inspection, VPN) is
interrupting or rewriting the ~100 MB Go SDK zip.

CI is unaffected (it runs gitleaks via the GitHub Action against ubuntu-latest
with clean network paths). So this is purely a local-hook problem.

## Options for the follow-up PR

1. **System-installed gitleaks.** `scoop install gitleaks` (or winget), then
   switch the hook to `language: system` with `entry: gitleaks protect --staged`.
   Pros: no Go download, fast, small. Cons: every contributor has to install
   gitleaks on their own machine; no pin in the config.

2. **Pin to an older hook rev that used prebuilt binaries.** Some older
   gitleaks hook revisions downloaded a prebuilt binary zip instead of
   building from Go source. If we can find a rev that works, we pin to it.
   Pros: no external install. Cons: likely stale gitleaks rules; still fragile
   to network issues.

3. **Fix the network path.** Identify the middlebox (corp proxy? antivirus?)
   and either whitelist `go.dev` or run the install off that network once,
   which caches the Go SDK. Pros: unblocks the canonical hook. Cons: depends
   on an environment Jon may not fully control.

4. **Replace gitleaks with a Python-native scanner.** `detect-secrets` has a
   mature pre-commit hook and installs via pip — no Go required. Tradeoff: a
   different ruleset than what CI runs, so local and CI drift.

## Recommended starting point

Option 1 (system-installed gitleaks) is probably the right landing spot. It
matches the tool CI uses, installs in one command on any OS, and sidesteps
the Go-SDK download entirely. Document the install step in README's "Local
development" section.

## Trigger to do this

Any time before the first external contributor joins, or before the first
secret-y thing lands in the repo (API keys for ingestion in M2 / M4). Not
urgent given CI coverage, but shouldn't sit parked past M2.
