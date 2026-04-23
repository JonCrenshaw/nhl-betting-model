# Other sports expansion

One-line: notes and constraints to preserve while building V1, so Phase 3 expansion is a data/modeling job, not a rewrite.

## Target ordering (rough)
1. MLB — high volume, strong free data (statsapi.mlb.com), prop-heavy, well-researched public models to borrow from
2. NBA — prop-heavy, lots of public edge historically, tracking data increasingly available
3. European soccer — enormous market, but complex due to league variety and draw outcomes
4. NFL — sharpest markets but highest subscriber demand
5. Other hockey leagues (KHL, SHL, AHL) — possible earlier as an NHL-customer differentiator

## Architectural rules to preserve
- Never put `nhl_` in a table or column name in silver or gold
- Never hardcode period structure, game duration, roster size, goal rate, or shot rate
- Market types belong in a `dim_market` with `sport_id` — don't create `nhl_moneyline` tables
- Feature engineering code is parameterized by sport where numerics differ
- Models are per-sport-per-market instances of a general training pipeline, not hand-coded per sport

## Non-obvious soccer complications
- Draw as a third outcome breaks binary models
- Congested fixtures + competitions (league, cup, European) create complex fatigue patterns
- Transfer windows mid-season destabilize team strength models
- Much more relevant external factors (weather, manager sackings, derbies)

## Non-obvious MLB complications
- Starting pitcher dominates game outcome — analogous to starting goalie but even more extreme
- Park factors matter a lot
- 162-game seasons create different sample-size dynamics

## Non-obvious NBA complications
- Load management and injury reports are a nightly circus
- Closing lines are very sharp in NBA — small public edge
- Props are where the edge lives

## Timing
Not until Phase 3. Listed here only so Phase 1/2 design preserves optionality.
