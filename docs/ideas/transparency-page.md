# Public transparency page as marketing moat

One-line: publish every pick the model has ever issued, with closing line and result, as the core public-facing credibility asset.

## Why this matters
- The tout industry is full of survivorship bias and selective disclosure
- A verified-at-close track record is rare and valuable
- Closing Line Value is more convincing to sophisticated customers than raw ROI
- It differentiates the product on its most defensible axis: honesty

## What the page should show
- Every pick, timestamped before close, with:
  - Market, side, odds at pick, odds at close, implied probability at each
  - Model probability
  - Theoretical edge at pick
  - Actual result
- Aggregate CLV over time with confidence bands
- Aggregate ROI with explicit "small sample" disclaimers
- Filter by sport, market type, tier

## Implementation notes
- Generated from the warehouse nightly; pure read model
- Must be tamper-evident — picks are published before game time and cannot be retroactively edited. Hash each pick at publish time.
- Accessible without login — this is marketing, not a paywalled feature

## Risks
- If the model underperforms for a stretch, the transparency works against us short-term. Accept this; it's the whole point.
