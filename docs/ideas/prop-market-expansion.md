# Prop market expansion

One-line: inventory of prop bet types to consider once the rate+simulator infrastructure exists.

## V1 starting set (from planning)
- Moneyline
- Total (O/U)
- Spread (puck line)
- Player shots on goal (O/U)
- Goal in first 10 minutes (yes/no)

## Natural next adds (derivable from the score simulator)
- Team totals
- First team to score
- Both teams to score
- 3-way moneyline (regulation)
- Double result (half-time / full-time)
- Race to N goals
- Winning margin buckets

## Player prop extensions
- Points (G+A)
- Assists
- Power-play points
- Blocked shots
- Hits
- Time on ice buckets (less common but sometimes available)
- Anytime goalscorer
- First/last goalscorer

## Goalie props
- Saves O/U
- Shutout yes/no
- Save percentage thresholds

## Live / in-play (V2+)
Live markets move fast and require a different infrastructure. Parked until V1 is proven.

## Design note
The score simulator + per-player distributional models should in principle price most of these from a single pipeline. New bet types mostly require new `dim_market` rows and a thin pricing function — not a new model.
