# Glossary

Domain terms used throughout this repo. Keep alphabetical.

### American odds
Quoting convention. `-150` means bet 150 to win 100. `+120` means bet 100 to win 120. Implied probability from American odds: for negative odds, `|odds|/(|odds|+100)`; for positive odds, `100/(odds+100)`.

### Bankroll
The money committed to betting. Risk management (Kelly sizing, flat betting, etc.) is always expressed as a fraction of bankroll.

### Brier score
Mean squared error between predicted probabilities and observed outcomes (0/1). Lower is better. Used alongside log loss as a calibration quality metric.

### Calibration
A model's predicted probabilities match observed frequencies. If the model says 60%, outcomes labeled 60% should actually occur 60% of the time. A model can be accurate without being calibrated; raw classifier outputs are rarely calibrated.

### Closing line
The final published odds before a market closes (typically at game start). The sharpest reference because all available information has been priced in.

### Closing Line Value (CLV)
The difference between the odds you bet at and the closing odds. Positive CLV means the market moved in your favor after you bet — strong evidence of edge, even in small samples. Our primary model-evaluation metric.

### Decimal odds
Quoting convention where the number is the multiplier on stake including stake return. `2.50` means bet 1 to receive 2.50 back (1.50 profit). Implied probability = `1 / decimal_odds`.

### Edge
The difference between your estimated true probability and the implied probability from the odds. Positive edge = positive expected value.

### Elo
A classic rating system updating team strengths after every game based on result and opponent rating. Simple, interpretable, a common baseline.

### Expected Value (EV)
For a single bet: `(p_win * profit_if_win) - ((1 - p_win) * stake)`. Positive EV means the bet is favorable in expectation.

### Expected Goals (xG)
Goal probability assigned to each shot based on its characteristics (location, shot type, rebound, etc.). A shot-quality metric that smooths the noise of actual goals.

### Implied probability
Probability implicit in a quoted price. For American `-150`, it's 60%. For decimal `2.50`, it's 40%. The sum across all outcomes exceeds 100% by the book's vig.

### Kelly criterion
Optimal bet sizing formula given edge and odds: `f* = (bp - q) / b` where `b` is net odds, `p` is win probability, `q = 1 - p`. Maximizes long-run log growth. Fractional Kelly (bet a fraction of the formula's suggestion) is safer given model uncertainty.

### Line movement
Change in odds between open and close. Sharp action causes measurable movement; tracking it is a feature source (did the book respond to signals that predate our bet?).

### Log loss
Negative log likelihood of predictions. Penalizes confident wrong predictions heavily. Standard metric for probability models.

### Market efficiency
Degree to which odds incorporate available information. Efficient markets are hard to beat; efficiency varies by book, sport, and market type.

### Moneyline
A straight bet on which team wins.

### No-vig probability
The implied probability of an outcome after removing the bookmaker's margin (vig). Useful for comparing odds across books and for establishing a market "true" probability.

### Puck line
Hockey's version of the spread. Almost always `±1.5` goals.

### Pinnacle
Sportsbook widely regarded as the sharpest in the world; rarely limits winners. Their no-vig line is often used as a benchmark for market efficiency.

### Platt scaling / isotonic regression
Post-hoc calibration methods applied to classifier scores to produce calibrated probabilities.

### Prop bet
A bet on something other than game outcome — player stats, in-game events, etc.

### Push
A bet that neither wins nor loses (e.g., an O/U bet on the exact total). Stake is returned.

### Rate model
A model that predicts per-time-unit quantities (goals/60, shots/60) rather than game totals directly. Rates are then consumed by a simulator to produce distributions over game outcomes.

### Sharp / square
"Sharp" bettors are sophisticated and profitable; "square" bettors are recreational. Books adjust lines in response to sharp action.

### Soft book / sharp book
Soft books (DraftKings, FanDuel, many US retail) are risk-averse and limit winners. Sharp books (Pinnacle, Circa, Bookmaker) accept large action but offer lower margins. Our V1 target limitation event is on a soft book.

### Total / Over-Under (O/U)
Bet on whether combined points/goals exceed a posted number.

### Vig / juice
The bookmaker's margin, baked into the odds. A `-110 / -110` market has ~4.5% vig.

### WAR (hockey)
Wins Above Replacement — a single-number player-value metric. Evolving Hockey's public WAR model is the best-known version.
