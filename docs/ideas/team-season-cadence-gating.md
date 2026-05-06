# Team-season manifest gating (M10 cadence wiring)

**Parked from PR-F2 design discussion, 2026-05-04.**

Sister to [`season-summaries-cadence-gating.md`](./season-summaries-cadence-gating.md).
PR-F2's `TeamSeasonLoader` is intentionally cadence-agnostic — it
fetches whenever called, writes a fresh bronze envelope per endpoint,
and (later, via PR-G) appends a manifest entry per
`(endpoint, scope_key)`. The "when to call it" decision lives one
layer up, in PR-G's backfill CLI and (later) M10's Dagster schedules.
This note parks the gating-logic decision so the M10 implementer
doesn't have to re-derive it.

## The wrinkle

PR-F2's two endpoints have **different natural cadences**:

| Endpoint | What changes | Reasonable cadence |
|----------|--------------|--------------------|
| `/v1/roster/{TEAM}/{SEASON}` | Trades, callups, IR, suspensions | Weekly; **daily** in the ~2-week trade-deadline window |
| `/v1/club-schedule-season/{TEAM}/{SEASON}` | Postponements (rare), reschedules | Once per season after schedule release; ad-hoc on postponement |

Manifest gating semantics differ across these three use cases:

- **Backfill of finalized seasons** *wants* the skip — neither endpoint
  changes for a closed season, so re-fetching is wasteful.
- **Weekly roster maintenance for the in-progress season** *wants* the
  refetch — players move between teams continuously, and a stale
  weekly snapshot is the data drift we're trying to avoid.
- **Schedule release for the upcoming season** is a one-shot — gate it
  via `manifest.has()` and refetch only on a known postponement event.

A uniform `manifest.has(endpoint, scope_key)` gate would correctly
suppress the backfill case but wrongly suppress the weekly roster
case. The same lesson PR-F1 learned for season summaries.

## The decision (option a)

**Three distinct M10 schedules, two of which gate via `manifest.has()`.**

Concretely, in M10:

1. **PR-G's backfill CLI** (and any one-shot rerun) iterates
   `(season, team)` pairs across the backfill window
   (`team_abbrevs(season)` enumerates the team set per season),
   calls `manifest.has(endpoint, scope_key)` per `(endpoint, season,
   team)` triple, and skips when present. `scope_key` is
   `f"{season}|{team}"` (per the M2 doc PR-F2 description). Idempotency
   matches PR-E's daily walker.
2. **Weekly + trade-deadline-daily roster** Dagster asset — **bypasses
   manifest gating entirely** for the `/v1/roster/...` endpoint of the
   current season. Fetches every team in `team_abbrevs(current_season)`,
   produces fresh bronze rows in distinct `ingest_date=YYYY-MM-DD/`
   partitions, manifest still records each fetch for run-history
   forensics. Trade-deadline-daily is a temporary override — bump
   schedule from weekly to daily for a fixed ~2-week window around the
   NHL trade deadline.
3. **Post-schedule-release club-schedule** Dagster asset — gates via
   `manifest.has()` for `/v1/club-schedule-season/...`. Triggered
   once per `(season, team)` after the NHL releases the schedule for
   the upcoming season. Postponement detection (a separate concern,
   probably via diff against the previous-day daily walker) can re-arm
   this asset by deleting the relevant manifest entry, or by passing
   a `force=True` flag through the Dagster asset.

## Why (a) and not "include cadence in scope_key"

The alternative (b) was: include the week in `scope_key` for the
roster endpoint (e.g. `f"{season}|{team}|wk={iso_week}"`) so each
weekly snapshot is its own logical unit and `manifest.has()` works
uniformly across both backfill and weekly use cases.

(a) wins for the same three reasons PR-F1's note enumerated:

1. **The schedule is the authority on freshness, not the manifest.**
   Mixing freshness into `scope_key` couples the manifest schema to
   the schedule's cadence — change the schedule and the manifest
   shape drifts.
2. **Backfill stays clean.** Under (b), backfill of finalized seasons
   would have to enumerate weeks too (or special-case "for completed
   seasons, scope_key=season|team; for in-progress, scope_key
   includes week"). Branching that breeds bugs.
3. **The bronze layer doesn't care.** Each weekly fetch already lands
   in a distinct `ingest_date=YYYY-MM-DD/` partition; bronze rows
   never collide on storage even when `scope_key` is the same. Silver
   picks the latest by `fetched_at_utc`.

## What changes in M10

Nothing changes in PR-F2. When M10 wires Dagster, the loader code
itself stays untouched; only the asset definitions differ:

```python
# pseudocode for M10
@dagster.asset(partitions_def=weekly_partitions)
def nhl_roster_weekly(context):
    season = current_season_id()
    for team in sorted(team_abbrevs(season)):
        # NB: bypass manifest gating — see
        # docs/ideas/team-season-cadence-gating.md
        loader.load_one(season, team)

@dagster.asset(partitions_def=season_partitions)
def nhl_team_season_backfill(context, season):
    for team in sorted(team_abbrevs(season)):
        roster_done = manifest.has(ROSTER_ENDPOINT_TEMPLATE,
                                   f"{season}|{team}")
        sched_done = manifest.has(CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
                                  f"{season}|{team}")
        if roster_done and sched_done:
            continue
        loader.load_one(season, team)

@dagster.asset(partitions_def=season_partitions)
def nhl_club_schedule_season_release(context, season):
    """One-shot per (season, team) after schedule release."""
    for team in sorted(team_abbrevs(season)):
        if manifest.has(CLUB_SCHEDULE_SEASON_ENDPOINT_TEMPLATE,
                        f"{season}|{team}"):
            continue
        loader.load_one(season, team)
```

Three distinct assets, same loader, different gating. That's the M10
shape — symmetrical to PR-F1's two-asset split, just with one more
asset because PR-F2 mixes two endpoints with different natural
cadences.

## Trade-deadline override

The trade-deadline-daily window is the most operationally sensitive
piece — too early or too late and we miss roster moves on the day they
happen. Two options for M10:

- **Hardcode a date range** per season (e.g. "March 1 → March 14, 2026
  for the 2025-26 season"). Simple, easy to audit, drifts annually.
- **Use a config-driven flag** (`is_trade_deadline_window: bool` in a
  Dagster resource) that an operator flips manually. More work but
  also explicitly captures the human-in-the-loop nature of "we know
  the deadline is today."

Lean: **hardcode the date range in a `TRADE_DEADLINE_WINDOWS` constant
in M10 alongside the asset definition.** Operators can override via
config in an emergency. Revisit if the NHL ever moves to a less
predictable trade-deadline schedule.

## Revisit triggers

- If the NHL deprecates `/v1/roster/...` in favor of a delta endpoint
  (only changed players returned), the weekly bypass gating may become
  unnecessary — the API itself becomes the freshness authority.
- If silver M3 wants **per-week roster diffs as a feature** (likely —
  injury and trade timing matter for game-level prediction), the bronze
  layout already supports it via `ingest_date`. No change needed here.
- If postponement detection ends up living in a separate ingest
  pipeline that knows about NHL postponement notices, schedule asset
  #3 could become event-driven instead of cron-scheduled. M10
  shouldn't pre-optimize for this.
