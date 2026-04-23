# Multi-model development and ensemble

One-line: train many model variants, narrow to the best, and/or ensemble, rather than committing to a single architecture.

## Motivation
Jon is explicitly open to higher upfront cost to develop multiple models and keep the best. This is the right instinct — model selection is notoriously hard, and ensembles often beat any single model.

## Candidate model families to explore
1. **Elo-family** (baseline, reproducing prior work) — cheap, interpretable
2. **Gradient boosted rate models** (XGBoost/LightGBM) predicting team scoring rates, fed into a score simulator
3. **Bivariate Poisson / negative-binomial** for goal totals and spreads
4. **Bayesian hierarchical** (PyMC or Stan) for player-level effects with partial pooling — great for sparse prop markets
5. **Learned player embeddings** from play-by-play sequences (skip-gram or small transformer) — V2 stretch
6. **Stacked ensembles** — meta-model that learns which base model to trust when

## Suggested process
- All models share the same gold-layer features (single source of truth)
- All models output calibrated probabilities for the same set of markets
- Evaluation harness runs them in parallel on identical backtest splits
- Primary metric: CLV on held-out games. Secondary: Brier, log loss.
- Drop models that don't beat the ensemble after full training

## Cost implications
- Training cost is modest (XGBoost on a laptop is fast)
- Storage/tracking matters — MLflow or W&B from day one
- Time cost to maintain many variants — probably collapse to 2–3 production models by end of V1

## Open questions
- Where do we draw the line between "promising variant" and "production model"?
- Do we combine via stacking (learn weights) or simple blending (averaging probabilities)?
