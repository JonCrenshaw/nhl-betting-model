# Sentiment analysis as a feature source

One-line: explore Reddit/X sentiment around teams, coaches, goalies as a leading indicator for market inefficiency.

## Why this is interesting
- Beat-writer tweets often move lines before official injury reports
- Reddit team sub sentiment may capture fanbase knowledge the market hasn't priced
- Potentially orthogonal to stats-based features — different error structure means useful in ensemble

## Why this is parked for V1
- Twitter/X API pricing is steep ($100+/mo tiers for anything useful)
- NLP pipeline adds complexity (feature extraction, embedding storage, drift monitoring)
- Unproven predictive value — have to test rigorously before investing

## If we revisit
- Start with Reddit (free via PRAW) to cheaply test the hypothesis
- Target a specific feature: volume of posts mentioning a key player in the 24h before puck drop, filtered to injury/lineup-related keywords
- Evaluate: does this feature improve calibration or CLV in holdout?
- Only invest in Twitter/X API if Reddit shows signal

## Open questions
- How much does sentiment lag the line vs. lead it?
- Beat-writer accounts vs. fan accounts — which carry signal?
- Language model choice: cheap sentence embeddings (sentence-transformers) vs. LLM zero-shot classification
