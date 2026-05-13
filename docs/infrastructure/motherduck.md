# MotherDuck

Operational runbook for the MotherDuck instance that hosts PuckBunny's silver
and gold dbt layers.

MotherDuck is set up. This doc captures how it was provisioned and how to do it
again — for a second environment, a rotation, or a recovery from a lost
credential.

Database: `puckbunny`. Provisioned May 2026. Owner: Jon.

Architecture context: [`docs/architecture/data-warehouse.md`](../architecture/data-warehouse.md).
Decision context: [ADR-0001](../decisions/0001-warehouse-stack.md) (why
MotherDuck over a self-hosted DuckDB on a VM).

---

## Why MotherDuck

MotherDuck was chosen as the production DuckDB host in ADR-0001. It gives us a
persistent, shared database at ~$10/month — no VM to manage, no always-on
process, and zero cold-start penalty for the dbt runs that matter (incremental
daily loads are the hot path). Full cost rationale and the M10 re-evaluation
trigger (self-hosted DuckDB on a Dagster VM) are in ADR-0001.

---

## Account and database provisioning — step by step

**Estimated time.** 15 minutes.

**1. Sign up at <https://app.motherduck.com/>.** Use the Google or GitHub OAuth
path — no separate password to manage.

**2. Create the database.** In the MotherDuck web UI:

- Click **New database** (or run `CREATE DATABASE puckbunny;` in the SQL editor).
- Name: `puckbunny`.
- Region: **US West 2** (AWS). This co-locates with the MotherDuck default
  region and reduces cross-region egress; R2 egress is free regardless.

**3. Create an access token.** In the MotherDuck web UI:

- Top-right avatar → **Settings** → **Access Tokens**.
- Click **Create token**.
- Name: `puckbunny-local-jon` (display name only; the env var is always
  `MOTHERDUCK_TOKEN`).
- Permissions: **Read/Write** — dbt needs to create and replace tables.
- Expiry: **No expiration** for now; rotate quarterly or at team/environment
  change.
- Copy the token immediately — it is shown only once.

**4. Add to `.env`.**

```dotenv
MOTHERDUCK_TOKEN=<paste token here>
```

`.env` is gitignored. Never paste the token into a committed file.

**5. Verify `profiles.yml` exists.** The dbt profile reads the token via
`env_var('MOTHERDUCK_TOKEN')`. Copy `dbt/profiles.yml.example` to
`dbt/profiles.yml` (project-local, gitignored) or to `~/.dbt/profiles.yml`
(user-global) and confirm the `prod` target looks like:

```yaml
prod:
  type: duckdb
  path: "md:puckbunny?motherduck_token={{ env_var('MOTHERDUCK_TOKEN') }}"
  threads: 4
  extensions:
    - httpfs
    - parquet
  settings:
    s3_endpoint: "{{ env_var('R2_ENDPOINT', '') }}"
    s3_region: "auto"
    s3_access_key_id: "{{ env_var('R2_ACCESS_KEY_ID', '') }}"
    s3_secret_access_key: "{{ env_var('R2_SECRET_ACCESS_KEY', '') }}"
    s3_url_style: "path"
```

---

## Smoke test

Run from the repo root with your virtualenv active:

```powershell
# Load .env into the shell first (if not using direnv)
Get-Content .env | ForEach-Object {
  if ($_ -match '^([^#][^=]*)=(.*)$') {
    [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2])
  }
}

# Confirm dbt can reach MotherDuck
uv run dbt debug --target prod --project-dir dbt --profiles-dir dbt
```

Expected output ends with `All checks passed!`. The first connection may take
5–10 seconds while MotherDuck warms up.

Alternatively, a quick Python one-liner:

```powershell
uv run python -c "import os; from dotenv import load_dotenv; load_dotenv(); import duckdb; con = duckdb.connect(f'md:puckbunny?motherduck_token={os.environ[\"MOTHERDUCK_TOKEN\"]}'); print(con.execute('SELECT current_database()').fetchone())"
```

Expected output: `('puckbunny',)`.

---

## Cold-start note

The first `dbt run --target prod` after provisioning will materialize all silver
tables from scratch by reading bronze Parquet from R2. For a full backfill
(10+ NHL seasons), expect **30–60 minutes**. This is a one-time cost; subsequent
incremental runs are fast (minutes).

---

## Cost posture

~$10/month at M3 volumes. Total V1 run-rate with R2 is ~$12–15/month —
inside the $50/month ceiling. Re-evaluate at M10 when a Dagster Cloud VM may
already be running; a self-hosted DuckDB on that VM could eliminate this line
item. See ADR-0001 D4 for the trigger.

---

## Token rotation

When to rotate:

- A credential is suspected leaked (e.g., found in a committed file — recover
  immediately).
- A new environment is added (Dagster Cloud at M10 gets its own token).
- Quarterly hygiene.

Procedure:

1. In MotherDuck → Settings → Access Tokens, create the new token first.
2. Update `MOTHERDUCK_TOKEN` in `.env` (and any deployed secret store).
3. Run the smoke test above with the new token.
4. Revoke the old token in MotherDuck.

---

## Troubleshooting

- **`UNAUTHENTICATED` / token error** — token was revoked or not loaded into
  the environment. Check `.env` is loaded and the variable name is exactly
  `MOTHERDUCK_TOKEN`.
- **`Database "puckbunny" not found`** — the database was not created in step
  2, or you are connecting to the wrong MotherDuck account. Log in to
  <https://app.motherduck.com/> and confirm the database exists.
- **dbt `profiles.yml` not found** — copy `dbt/profiles.yml.example` to
  `dbt/profiles.yml` and fill in your token via the env var. Do not hardcode
  the token in `profiles.yml`.
- **`project path ... not found`** — always pass `--project-dir dbt` when
  running dbt from the repo root.
- **Slow first query** — MotherDuck has a short cold-start; 5–10 seconds on
  first connection is normal.
- **`httpfs` extension missing** — ensure the `extensions: [httpfs, parquet]`
  block is present in your `profiles.yml` prod target. dbt-duckdb installs
  them automatically if listed.
