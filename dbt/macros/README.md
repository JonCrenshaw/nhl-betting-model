# Macros

Reusable Jinja + SQL snippets. Project-local macros live here; third-party
macros come in via `packages.yml` and `dbt deps`.

Organize by concern as the directory grows:
- `macros/tests/` — custom generic tests
- `macros/utils/` — small SQL helpers (date math, unioning staging models)
- `macros/sources/` — anything specific to ingesting a particular source

Every macro should have a docstring-style comment at the top explaining what
it does, what arguments it takes, and any assumptions it makes.
