#!/usr/bin/env bash
#
# Runs once when the Dev Container is created. Installs the project-level
# toolchain on top of the base image:
#   1. uv (Python package manager, pinned via the install script's latest).
#   2. All project dependencies, from the committed uv.lock.
#   3. The pre-commit git hook, so commits inside the container run the same
#      hooks as local / CI.
#
# Idempotent: safe to re-run (e.g. after a container rebuild).

set -euo pipefail

# .venv is a named Docker volume (see devcontainer.json "mounts"). Named
# volumes are created root-owned on first mount; chown to the non-root dev
# user so `uv sync` can write into it.
if [ -d .venv ]; then
  sudo chown -R "$(id -u):$(id -g)" .venv
fi

echo "==> Installing uv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv's installer writes to ~/.local/bin. Make sure *this* shell picks it up.
  export PATH="$HOME/.local/bin:$PATH"
else
  echo "uv already present: $(uv --version)"
fi

echo "==> Syncing dependencies (--frozen: fails if uv.lock drifted from pyproject.toml)"
uv sync --frozen

echo "==> Checking pre-commit git hook"
# Hook installation is the host's responsibility. Running `pre-commit install`
# from inside the container on a Windows host bind-mount causes real harm:
# pre-commit writes a new hook file embedding a Linux Python path, then fails
# on chmod (EPERM via NTFS translation). The write already happened, so the
# file is left pointing at a path that doesn't exist on the Windows host.
# Subsequent commits from Windows then fail with "pre-commit not found".
#
# We skip install if a hook already exists, and attempt install only when
# there's nothing there yet (e.g. fresh container without a prior host
# install). Even then, if it fails, we don't treat it as fatal.
if [ -f .git/hooks/pre-commit ]; then
  echo "pre-commit hook already present (managed by the host). Leaving untouched."
else
  if uv run pre-commit install 2>/dev/null; then
    echo "pre-commit hook installed."
  else
    echo "pre-commit install did not complete; run 'uv run pre-commit install'"
    echo "from your host shell (PowerShell/bash) to set up the hook."
  fi
fi
echo "Manual check in the container: 'uv run pre-commit run --all-files'"

echo ""
echo "==> Dev container ready."
echo "    Next steps:"
echo "      - Create dbt/profiles.yml from dbt/profiles.yml.example if you intend to run dbt."
echo "      - See docs/development.md for the full workflow."
