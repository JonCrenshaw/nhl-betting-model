---
description: Audit a feature or model for time-leakage and other peeking hazards.
---

## When to use

Before merging any feature-engineering code (Python or dbt), and any time a backtest result looks suspiciously good. The "no peeking" rule in `CLAUDE.md` is the single most important constraint on this project — a leakage bug invalidates every downstream metric, including CLV.

## Why it exists

Time-leakage is silent. Tests pass, metrics look great, and the bug only surfaces when live performance diverges from backtest. Running this audit explicitly turns a quiet failure mode into a checkpoint.

## Behavior

Ask Jon which file (or dbt model) to audit, then check for:

1. **As-of-today joins.** Joins to dimensions or feature tables that don't filter to the timestamp of the target row. Flag any join where the joined table could have been updated after the target's `as_of_ts` (rosters, injuries, lineups, season-to-date stats are the usual culprits).
2. **Aggregations crossing the target boundary.** Window functions or group-bys whose frame includes rows at or after the target. Rolling features must end strictly before the target timestamp.
3. **Label leakage in feature columns.** Any feature derived from the outcome itself or a downstream consequence of it (e.g., final score components in a pre-game feature).
4. **Snapshot freshness mismatch.** Dimensions joined "as of today" instead of "as of game time."
5. **Test/train contamination.** Any sample appearing in both sets, or a random split applied to time-series data. Time-based splits only.
6. **Implicit data joins via primary keys that change post-event.** If a key is reassigned after the event (e.g., a game ID that gets corrected), the join can pull in post-event data without obvious indication.

## Output

Produce:

- A line-by-line punch list with `file:line` references and a one-sentence explanation per finding.
- A verdict: **PASS** / **FAIL** / **NEEDS HUMAN REVIEW**.
- If PASS, a short note on what you actively verified (so the audit isn't a rubber stamp). For example: "Verified the rolling window in `src/.../rolling.py:42` ends at `target_ts - 1ms` and excludes the target row itself."

## References

- `CLAUDE.md` → "Testing requirements" → "no peeking" rule
- `CLAUDE.md` → "Do / Don't" → "Don't peek at future data in feature construction"

If the file doesn't exist yet (e.g., feature engineering hasn't started — pre-M5), say so and offer to draft a leakage-resistant template instead.
