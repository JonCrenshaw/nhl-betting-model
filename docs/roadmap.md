# Roadmap

Draft. Dates are indicative only, based on ~10 hrs/week solo time starting April 2026.

---

## Phase 1 — Proof of Concept

**Goal.** Prove the model has real edge. V1 is complete when a major sportsbook limits Jon's account after live betting the model's picks.

**Target window.** April 2026 → start of NHL 2026–27 regular season (October 2026), with live betting through that season.

**Secondary success criteria.**
- Positive Closing Line Value across a statistically meaningful bet sample.
- Automated daily pipeline running unattended.
- Operational cost under $50/month.
- Architecture passes a "port to MLB" thought experiment — no rewrite required, only new loaders.

### Milestones

| # | Milestone | Exit criteria | Rough effort |
|---|-----------|---------------|--------------|
| M1 | Repo & local environment | GitHub repo, devcontainer, `uv` project, dbt scaffold, pre-commit hooks, CI running tests & linters on PR | 1–2 weeks |
| M2 | NHL API ingestion | Historical game, skater, goalie, and PxP data loaded into bronze. Incremental daily loader. Partitioned Parquet in object storage. | 2–3 weeks |
| M3 | Silver layer & sport-agnostic schema | Conformed entities: `sport`, `league`, `team`, `player`, `game`, `event`, `market`, `odds`. dbt tests passing. | 2 weeks |
| M4 | Odds ingestion | The Odds API daily pulls into bronze → silver `odds` table. Historical odds dataset purchased and loaded. | 1–2 weeks |
| M5 | Feature engineering v1 | Gold-layer features: team strength (Elo, xG-based), goaltender form, lineup/injury adjustment, rest/travel/fatigue, home-away, b2b. | 3–4 weeks |
| M6 | Baseline Elo+ model | Reproduce prior Elo work in this pipeline. Backtest harness operational. First CLV numbers logged. | 1–2 weeks |
| M7 | Rate model + score simulator | Bivariate Poisson (or comparable) over rate predictions. Generate full game distributions; price ML / total / spread from one model. | 3–4 weeks |
| M8 | Player prop extension | Shots, goals-in-first-10, 1+ other prop priced from player distributional models layered on team rates. | 2–3 weeks |
| M9 | Calibration & bet selection | Platt/isotonic calibration. Kelly fractional or configurable sizing. Pick generation logic with explicit EV threshold. | 1–2 weeks |
| M10 | Daily automated pipeline | Dagster assets for full ingest → features → predictions → picks → storage. Runs on schedule without Jon's laptop. | 2 weeks |
| M11 | Internal dashboard | Streamlit or Evidence page showing today's picks, current CLV, backtest history, model health. | 1 week |
| M12 | Paper trade | Log simulated bets for 4–8 weeks of live games. Evaluate CLV distribution. | Ongoing during NHL season |
| M13 | Live betting & limitation event | Begin betting real money on one or more major books. Target: account limitation. | Ongoing during NHL season |

### Out of scope for Phase 1
- Public-facing website or app
- Authentication, subscriptions, billing
- Sentiment/NLP features (Reddit, Twitter beat writers) — parked in ideas
- Non-NHL sports
- Sophisticated lineup scrapers (use paid source if needed)

---

## Phase 2 — Productionalize & market

**Goal.** Convert a working model into a subscription product with credible public-facing metrics.

**Trigger to begin.** Phase 1 success criterion met (or demonstrably close), with a backtest/paper-trade record strong enough to stand behind publicly.

### Milestones (draft, not yet scheduled)

- P1 — Frontend foundation (Next.js + Netlify), design system, marketing site
- P2 — Auth + Stripe billing + subscription tiers
- P3 — Public API between warehouse and frontend, cached reads, rate limiting
- P4 — Subscriber dashboard: daily picks, line tracking, CLV-to-date
- P5 — **Public transparency page.** Every pick ever issued, with its closing line and result. This is the marketing moat.
- P6 — Content: blog, onboarding education, responsible-gambling resources
- P7 — Paid acquisition tests with strict unit-economics tracking
- P8 — Customer support + community (Discord or similar)

### Open questions for Phase 2
- Pricing tiers and what differentiates them (sports coverage? bet types? bet sizing guidance?)
- Legal structure and jurisdictional restrictions (state-by-state in US, country-by-country elsewhere)
- Liability framing — we do not place bets for users, we publish picks

---

## Phase 3 — Multi-sport expansion (future)

**Principle.** Phase 1 and 2 infrastructure is sport-agnostic. Expansion = new data loaders + new feature engineering + new model training, with zero rewrites downstream.

**Likely order of expansion**, based on combination of data availability, market inefficiency, and subscriber appeal:
1. MLB (high game volume → many betting opportunities; prop-heavy; strong free data via statsapi.mlb.com)
2. NBA (player-prop-heavy markets; lots of public edge historically)
3. European soccer (huge market; complex due to league variety)
4. NFL (sharpest market; hardest to beat but highest subscriber demand)
5. Other hockey leagues (KHL, SHL, AHL) — may come earlier as a differentiator

### Architectural implications to preserve
- `sport` and `league` as first-class columns throughout silver/gold
- Models parameterized by sport; no hardcoded NHL period structure, roster size, goal rate, etc.
- Market-type registry that can represent arbitrary bet structures (threshold, handicap, exact-score, parlay)
- Odds ingestion pipeline that accepts new sports by config, not code change

---

## Living document

This roadmap is a draft. We revisit after each milestone. Changes to milestone scope or ordering should be noted in the relevant ADR, not hidden in a silent edit here.
