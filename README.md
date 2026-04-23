# PuckBunny

A predictive modeling and betting analytics product. Identifies +EV (positive expected value) bets by comparing model-implied probabilities against sportsbook odds.

**Phase 1 scope: NHL.** The data model is sport-agnostic from the silver layer up, so MLB, NBA, NFL, and European soccer can be added in Phase 3 without a rewrite. Note: the name "PuckBunny" is hockey-specific; multi-sport expansion will prompt a branding discussion (parent brand, rename, or per-sport sub-brands).

## Current status
**Phase 1 — Proof of Concept** (planning stage)

## The short version
1. Pull player, team, lineup, injury, and game data from NHL and third-party sources into a sport-agnostic data warehouse.
2. Build calibrated probabilistic models for game and player markets (moneyline, total, spread, and select props).
3. Compare model probabilities to sportsbook odds to surface +EV bets.
4. Track Closing Line Value (CLV) as the primary measure of edge; paper-trade and then live-bet through a full NHL season.
5. Graduate to a subscription product once edge is demonstrable.

## Primary success criterion for V1
**Get limited or banned on at least one major sportsbook** through personal betting. That is the only unambiguous signal that the model has real edge.

## Secondary success criteria
- Positive CLV across a statistically meaningful sample of bets
- Fully automated daily pipeline (ingest → features → predictions → picks)
- Cost < $50/month excluding one-time historical odds data purchase
- Architecture that ports to MLB / NBA / NFL / soccer with only loader-level changes

## Where to start
- [CLAUDE.md](./CLAUDE.md) — working agreements for Claude Code sessions
- [docs/working-with-claude.md](./docs/working-with-claude.md) — how Jon gets the most out of Claude across sessions
- [docs/roadmap.md](./docs/roadmap.md) — phased milestones and timeline
- [docs/architecture/data-warehouse.md](./docs/architecture/data-warehouse.md) — warehouse design
- [docs/data-sources.md](./docs/data-sources.md) — catalog of external data sources
- [docs/costs/](./docs/costs/) — cost tracking (budget, recurring services, expense log)
- [docs/decisions/](./docs/decisions/) — Architecture Decision Records (ADRs)
- [docs/ideas/](./docs/ideas/) — parking lot for unscoped ideas

## Local development

Python 3.12, managed with [`uv`](https://docs.astral.sh/uv/). After cloning:

```
uv sync
```

This installs all dependencies (including dev extras) from `uv.lock` into a local `.venv`. The lockfile is committed to guarantee reproducible installs across machines and CI. If you update dependencies in `pyproject.toml`, run `uv sync` again to refresh the lockfile and commit both files together.

## Ownership
- Owner: Jon Crenshaw
- Time budget: ~10 hours/week
- Budget (V1): ~$50/month operational; ~$200–500 one-time for historical odds data
