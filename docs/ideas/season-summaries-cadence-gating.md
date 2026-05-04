# Season-summaries manifest gating (M10 cadence wiring)

**Parked from PR-F1 design discussion, 2026-05-01.**

PR-F1's `SeasonSummariesLoader` is intentionally dumb about cadence —
it fetches whenever called, writes a fresh bronze envelope, and appends
a manifest entry. The "when to call it" decision lives one layer up,
in PR-G's backfill CLI and (later) M10's Dagster schedule. This note
parks the gating-logic decision so the M10 implementer doesn't have to
re-derive it.

## The wrinkle

The loader records manifest entries with `scope_key = season` (e.g.
`"20242025"`), matching the PR-F0 spike's recommendation that one
manifest entry = one logical unit of work. That's correct for backfill
of *finalized* seasons — re-fetching them is wasteful, and
`manifest.has(endpoint, season)` is the right skip-check.

But the same gating logic is **wrong** for the weekly maintenance
schedule on the *in-progress* season:

- Week 1: schedule fires, fetches `/skater/summary?seasonId=20252026`,
  manifest now has `(/stats/rest/en/skater/summary, 20252026)`.
- Week 2: schedule fires, `manifest.has(...)` returns `True`, fetch
  is skipped — but the data has changed (players have played more
  games), and we want a fresh weekly snapshot.

So the manifest semantics differ by use case: backfill *wants* the
skip; weekly maintenance *wants* the refetch.

## The decision (option a)

**Backfill gates via `manifest.has()`; weekly schedule bypasses
manifest gating entirely (always fetches).**

Concretely, in M10:

- **PR-G's backfill CLI** (and any one-shot rerun) iterates seasons,
  calls `manifest.has(endpoint, season)` per `(endpoint, season)`
  pair, and skips when present. Same idempotency story as PR-E's
  daily walker.
- **M10's weekly Dagster asset** for season summaries does *not*
  consult the manifest — it always calls `loader.load_one(season)`
  for the current season. The manifest still records every weekly
  fetch (good for run-history forensics) but doesn't gate.
- **Post-SCF capture** is a one-shot scheduled task that also
  bypasses gating (we want one final snapshot regardless of what
  the manifest already has).

## Why (a) and not (b)

The alternative (b) was: include the week in the scope_key
(e.g. `f"{season}|wk={iso_week}"`), so each week is its own logical
unit and `manifest.has()` works uniformly across both use cases.

(a) wins because:

1. **The schedule is the authority on freshness, not the manifest.**
   The manifest's job is "did this fetch succeed," not "is this data
   still current." Mixing those concerns means the manifest's
   `scope_key` shape becomes coupled to the schedule's cadence —
   change the schedule and the manifest schema drifts.
2. **Backfill stays clean.** Under (b), backfill of completed seasons
   would have to enumerate weeks too (or special-case "for completed
   seasons, scope_key=season; for in-progress, scope_key includes
   week"). That's the kind of branching that breeds bugs.
3. **The bronze layer doesn't care.** Each weekly fetch already lands
   in a distinct `ingest_date=YYYY-MM-DD/` partition, so bronze rows
   never collide on storage even if the manifest scope_key is the
   same. Re-running the same week's fetch produces a second bronze
   row in the same ingest_date partition — defensible (it's a true
   re-fetch) and queryable (silver picks the latest by
   `fetched_at_utc`).

## What changes in M10

Nothing changes in PR-F1. When M10 wires Dagster, the loader code
itself stays untouched; only the asset definitions differ:

```python
# pseudocode for M10
@dagster.asset(partitions_def=weekly_partitions)
def nhl_season_summaries_weekly(context):
    season = current_season_id()
    # NB: bypass manifest gating — see
    # docs/ideas/season-summaries-cadence-gating.md
    loader.load_one(season)

@dagster.asset(partitions_def=season_partitions)
def nhl_season_summaries_backfill(context, season):
    # Gate via manifest — finalized seasons don't need re-fetch.
    if manifest.has(SKATER_SUMMARY_ENDPOINT_TEMPLATE, season):
        context.log.info("skipping already-loaded season", season=season)
        return
    loader.load_one(season)
```

Two distinct assets, same loader, different gating. That's the M10
shape.

## Revisit triggers

- If we ever want **incremental within-week updates** (e.g. mid-week
  re-fetch after a notable game), revisit (b) — week-keyed scope_key
  becomes more useful.
- If the weekly cadence produces **noticeable manifest bloat** (>10k
  entries for season summaries alone over multiple seasons), revisit
  (a) — we may want a separate manifest namespace or a periodic
  compaction. But at ~52 weeks × 3 endpoints × N current seasons,
  this is years away.
- If silver M3 wants **per-week snapshot diffs as a feature**
  (unlikely but possible), the bronze layout already supports it via
  `ingest_date` — no change needed here.
