# Data Sources Catalog

Running catalog of external data sources considered, adopted, or parked. Update as we go.

---

## Hockey play / stats data

| Source | What | Access | Cost | Status | Notes |
|--------|------|--------|------|--------|-------|
| NHL API (statsapi.web.nhl.com / api-web.nhle.com) | Games, rosters, skater/goalie stats, play-by-play, schedule | Public HTTP | Free | **Primary V1** | Rate limits unofficial but real; be polite. Schema has changed historically, so wrap behind a thin client. |
| MoneyPuck | xG models, shot-quality data, team & player metrics | Scrapable CSVs | Free | **V1 adopt** | Widely respected public xG. Good supplementary features. |
| Natural Stat Trick | Advanced team & player metrics, on-ice numbers | Scrapable HTML, paid plus | Free / ~$5/mo | V1 optional | Useful for on-ice xG with/without, line combinations. |
| Evolving Hockey | Best public WAR/RAPM models, xG | Subscription | ~$10/mo | V2 adopt | High-quality model features. Worth paying for in V2. |
| Hockey Reference | Historical stats, biographical data | Scrapable | Free | Fallback | Good for backfill and sanity checks. |
| HockeyViz | Visualizations, some data | Web | Free | Parked | More visualization than pipeline data. |

## Lineups and injuries

| Source | What | Access | Cost | Status | Notes |
|--------|------|--------|------|--------|-------|
| DailyFaceoff | Projected starting lineups, starting goalies | Scrapable | Free | **V1 target** | Most reliable public projected lineups. Terms of service to review. |
| LeftWingLock | Line combinations, goalie rotations | Scrapable | Free | V1 alternative | Cross-check against DailyFaceoff. |
| Rotowire | Lineups, injuries, news | Paid | ~$15/mo | V2 upgrade | Aggregated, more reliable, API available on some plans. |
| NHL Injury reports | Official injury designations | Via NHL API / team feeds | Free | V1 adopt | Notoriously conservative; always a day behind beat-writer info. |
| Beat-writer X/Twitter feeds | Real-time lineup/injury news | Twitter/X API | $100+/mo tiers | V2 consider | Cost is the blocker. Alternative: scrape curated list of blogs. |

## Odds

| Source | What | Access | Cost | Status | Notes |
|--------|------|--------|------|--------|-------|
| The Odds API | Current odds across many books and markets | REST API | Free tier (500 req/mo), $30–59/mo live tiers | **V1 primary** | Standard choice. Coverage of props varies by sport. |
| OddsJam | Deep odds incl. props, arbitrage feeds | REST API | $100+/mo | V2 consider | Better prop coverage. Expensive for V1. |
| SportsGameOdds | Odds API alternative | REST API | Mid-tier | V2 benchmark | Evaluate as TheOddsAPI alternative. |
| Pinnacle scraping | Sharp reference line | Scrape or paid reseller | Varies | **V1 reference** | Pinnacle is the market, even if we bet elsewhere. Their no-vig line is our benchmark for model edge. |
| Historical odds dataset | Past seasons of closing lines | One-time purchase | $200–500 | **V1 mandatory** | Without this, backtests are meaningless. Vendor TBD — research SportsDataIO, BetLabs, Kaggle datasets, Action Network exports. |

## Sentiment / alternative data (V2+)

| Source | What | Status | Notes |
|--------|------|--------|-------|
| Reddit (r/hockey, team subs) | Post volume, sentiment around key players/games | Parked | Cheap to pull via PRAW. Predictive value unproven — test as feature before investing. |
| NHL-beat-writer X lists | Injury/lineup news | V2 | Subject to X API cost. |
| Google Trends | Public attention signals | Parked | Some research shows predictive value for market inefficiencies. |

## Travel / venue / weather

| Source | What | Status | Notes |
|--------|------|--------|-------|
| Arena latitude/longitude + altitude | Per-game travel distance, altitude (Denver), timezone change | **V1 adopt** | One-time static dim table. Trivial to build. |
| Country/border crossings | Flag for US/CAN game-to-game travel | **V1 adopt** | Derived from venue metadata. |
| Flight durations | Derived from great-circle distance or schedule lookup | V1 optional | Can approximate from distance. |

## NOT planning to use (for V1)

- NHL official data APIs that require partnership agreements
- Sportlogiq / Stathletes (tracking data) — enterprise-priced
- Instinct — subscription model similar to Evolving Hockey
- Any scraper that requires bypassing anti-bot protections — legal and operational risk

---

## Data-source adoption checklist

Before onboarding a new source:
1. Terms of service reviewed. Note any prohibitions on commercial use.
2. Rate limits documented and respected.
3. Loader wrapped in a client module with retries, backoff, and structured logging.
4. Bronze schema committed; changes to that schema are a versioning event.
5. Data quality tests in dbt (expected row counts, nullability, value ranges).
6. Cost and quota monitoring hooked into the loader.
7. ADR written if this is a "big" source (primary signal, paid service, or replaces an existing source).
