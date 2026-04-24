# ADR-0002: Development environment via Dev Containers

**Status.** Proposed
**Date.** 2026-04-23
**Deciders.** Jon

## Context

By the end of M1 we have a workable local setup: uv for Python, pre-commit
for hooks, dbt + sqlfluff for the warehouse surface. This works on Jon's
Windows + PowerShell machine today, but two realities make a standardized,
reproducible dev environment worth formalizing:

1. **Platform-specific issues have already bitten us.** PR 2 hit an SSL /
   BadZipFile failure downloading the Go SDK for the gitleaks pre-commit
   hook, specific to Jon's Windows network path. Having a Linux
   container-backed alternative would have sidestepped that entirely.
2. **Phase 2 contributors / reviewers / future-Jon-on-different-hardware.**
   Any non-trivial project benefits from "clone and it works." Writing down
   how the environment is built before the team grows is cheaper than
   archaeologizing shell histories later.

## Options considered

**Keep local-only.** Document the tooling, expect each contributor to set up
their own machine. Cheap, flexible. Cons: platform drift, onboarding cost
scales with contributors, hard-to-reproduce bugs.

**VM image.** Vagrant or similar. Pros: total reproducibility. Cons: heavy
(multi-GB), slow to boot, poor IDE integration, obsolete pattern in 2026.

**Dev Containers (`.devcontainer/devcontainer.json`).** The [Dev Containers
specification](https://containers.dev/) standardizes container-backed dev
environments. Supported natively by VS Code and GitHub Codespaces, also
consumable by IntelliJ and the `devcontainer` CLI. Pros: fast (container
starts in seconds), identical inside/outside VS Code, same config powers
Codespaces so Jon (or any contributor) can get a browser-based environment
in one click. Cons: requires Docker Desktop locally (Jon already has it
via other work), and a small amount of maintenance when base images or
features update.

**GitHub Codespaces only.** Skip local devcontainer, use Codespaces
exclusively. Pros: zero local setup. Cons: monthly compute cost against
the Codespaces quota, requires network to work at all, harder to iterate
on fast feedback loops, lock-in to GitHub's hosted env.

## Decision

Adopt the Dev Containers specification via `.devcontainer/devcontainer.json`.
The same config powers both local containers (VS Code / `devcontainer` CLI)
and GitHub Codespaces, so this is one artifact serving two use cases.

**Local development remains valid and supported.** The devcontainer is
additive — Jon's current PowerShell + local-uv workflow continues to work
and is documented in `docs/development.md` as the primary path. The
devcontainer is a fallback when platform issues bite, a clean slate for
reviewers, and the path Codespaces will use once we turn it on.

### What's in it

- Base image: `mcr.microsoft.com/devcontainers/python:1-3.12-bookworm`.
  Tracks our `.python-version` and `pyproject.toml`'s Python requirement.
- Feature: `ghcr.io/devcontainers/features/github-cli`. `gh` for PR
  workflows from inside the container.
- `postCreateCommand` runs `.devcontainer/post-create.sh`, which installs
  uv, runs `uv sync --frozen` against the committed lockfile, and installs
  the pre-commit git hook.
- VS Code extensions curated to the project's surface: ruff, mypy,
  dbt-power-user, sqlfluff, github-actions.
- `uv sync --frozen` (not bare `uv sync`) so a drifted lockfile fails the
  container build instead of silently regenerating — the same strictness we
  want from CI.

### What's intentionally not in it

- No Node.js / npm. Phase 2 frontend tooling will be added when we start
  that work, likely as a second service in `docker-compose` or a separate
  Dev Container configuration.
- No Postgres / Redis / orchestrator. DuckDB is a library, not a server.
  When M10 wires up Dagster we revisit — Dagster may run fine in the same
  container or may want a dedicated compose service.
- No `.dbt/profiles.yml`. Credentials and connection config are
  per-contributor. Post-create prints a reminder to copy from
  `dbt/profiles.yml.example`.

## Consequences

**Positive.**
- One-click onboarding in VS Code ("Reopen in Container") and one-click
  browser dev via Codespaces.
- Platform-specific bugs have an out: run the Linux container, bypass
  Windows network / filesystem gremlins.
- Same pre-commit config runs in both local and container contexts, so
  commits from either produce the same hook behavior.
- The config is version-controlled. Every change to the dev environment is
  a reviewable diff.

**Negative.**
- One more surface to maintain. Base image tag needs a bump on Python
  version changes; features and extensions will drift if left alone.
- Docker Desktop dependency for local container use. Jon already has this;
  a future Mac or Linux contributor will need it.
- Codespaces, if enabled, metered against GitHub quota. Not yet an issue
  because Codespaces isn't turned on; revisit when we do.

**Neutral.**
- The devcontainer Dockerfile pattern (custom image) is intentionally
  avoided in favor of `image:` + features + postCreate. If we outgrow that,
  moving to a Dockerfile is a mechanical change inside `.devcontainer/`.

## Revisit trigger

Revisit this decision if any of:
- Dev Containers spec or the underlying base images become unmaintained.
- We need services (Postgres, Redis, Dagster server) alongside the main
  container — docker-compose then becomes the better primitive.
- Codespaces cost becomes material.
- Frontend (Phase 2) needs its own tooling and we want to unify or split
  the dev env.
