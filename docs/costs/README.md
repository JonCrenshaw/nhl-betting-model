# Cost tracking

How we track operational costs for PuckBunny. Line-item per transaction, version-controlled in the repo.

## Why this exists

- CLAUDE.md rule: V1 operational budget ceiling is ~$50/month. We can only enforce a budget we actually measure.
- Versioned history of every project expense, so price changes and surprise charges are auditable.
- Queryable via DuckDB once the warehouse is up; eventually ingests into the cost-monitoring mart alongside pipeline metrics.

## Budgets

| Category | V1 target | V1 ceiling | Notes |
|---|---|---|---|
| Monthly operational | $50 | $100 | Everything recurring combined |
| One-time (historical odds) | $200–500 | $500 | Non-recurring; amortize mentally over the season |
| AI / tooling | included in monthly | $50 alone | Claude subscription, developer tooling |

If monthly run-rate is trending above the target, flag it in the next session and decide: absorb, re-scope, or adjust the target via an ADR.

## Recurring services

Current state as of project start. Update this table when services are adopted, dropped, or repriced.

| Service | Vendor | Monthly cost | Status | Notes |
|---|---|---|---|---|
| Claude subscription | Anthropic | varies | Active | Primary AI tooling; billed monthly |
| GitHub | GitHub | $0 | Active | Personal free tier |
| Domain registration | Netlify | – | Pre-existing | Already owned; renewal cost TBD |
| Dagster Cloud (Solo) | Dagster | $0 | Planned (M10) | Free tier for solo orchestration |
| MotherDuck (Standard) | MotherDuck | ~$10 | Planned (M1–M2) | Hosted DuckDB; see ADR-0001 |
| Cloudflare R2 | Cloudflare | ~$2–5 | Planned (M1–M2) | Object storage, zero egress fees |
| The Odds API | The Odds API | $0 → ~$30–60 | Free tier now; paid when live-betting | See docs/data-sources.md |

## One-time purchases planned

| Item | Est. cost | Status | Notes |
|---|---|---|---|
| Historical odds dataset (3–5 seasons) | $200–500 | Planned (M4) | Vendor research ongoing; see docs/data-sources.md |

## How to record a transaction

Add a row to `expenses.csv` when an invoice hits. Columns:

- **date** — `YYYY-MM-DD` of the charge on the invoice
- **vendor** — who charged you (e.g., `Anthropic`, `MotherDuck`, `Cloudflare`)
- **category** — one of: `AI/Tools`, `Infra`, `Data`, `Domain`, `Services`, `Other`
- **amount_usd** — amount in USD. If billed in another currency, convert using the exchange rate on the invoice date and note the original amount + rate in `notes`.
- **billing_period** — `YYYY-MM` for recurring subscriptions; `YYYY-MM-DD` for one-time purchases
- **invoice_ref** — invoice number, URL, or account ID. Leave empty if none.
- **notes** — free text. Anything future-you would want to know.

Commit each addition in its own commit with a conventional message:

```
chore(costs): log April Anthropic invoice
```

Keep commits atomic — one invoice per commit makes `git blame` useful if you need to trace when a charge changed.

## How to query

Once DuckDB is installed locally (M1), the CSV is query-able directly without any ETL:

```sql
-- Monthly totals by category
SELECT
  billing_period,
  category,
  SUM(amount_usd) AS total
FROM 'docs/costs/expenses.csv'
GROUP BY billing_period, category
ORDER BY billing_period DESC, total DESC;

-- Rolling 3-month run-rate
WITH monthly AS (
  SELECT billing_period, SUM(amount_usd) AS total
  FROM 'docs/costs/expenses.csv'
  WHERE LENGTH(billing_period) = 7   -- recurring entries only
  GROUP BY billing_period
)
SELECT
  billing_period,
  total,
  AVG(total) OVER (ORDER BY billing_period ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS rolling_3mo_avg
FROM monthly
ORDER BY billing_period DESC;

-- Year-to-date spend
SELECT SUM(amount_usd) AS ytd FROM 'docs/costs/expenses.csv'
WHERE billing_period LIKE '2026-%';
```

Before DuckDB is installed, the CSV is simple enough to open in Excel, Google Sheets, or any text editor.

## Future work

Parked items, not active yet:
- Ingest `expenses.csv` as a bronze-layer source in the warehouse so budgets join with pipeline metrics.
- Automate alerting when monthly run-rate crosses 80% of the ceiling.
- Evaluate whether to pull invoices automatically via Stripe-style webhooks once more vendors are involved.
