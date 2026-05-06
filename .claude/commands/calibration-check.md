---
description: Run a calibration check on a trained model's predictions.
---

## When to use

After training a new model, after retraining an existing one, and any time predictions are about to feed bet-selection logic. The "calibrated probabilities are required" principle in `CLAUDE.md` means uncalibrated outputs cannot be trusted as probabilities — running this check is the gate.

## Why it exists

Raw classifier outputs are scores, not probabilities. Bet-sizing and EV calculations assume calibrated probabilities; if calibration drifts, EV estimates drift with it and we end up sizing bets off a number that doesn't mean what the math thinks it means.

## Behavior

Ask Jon for:

- Path to the model artifact, or to its predictions on a held-out sample
- The target variable and the held-out time window

Steps:

1. Load the held-out predictions and actuals.
2. Bin predictions (deciles by default; use 20 bins or quintiles instead if sample size warrants) and compute, per bin: count, mean predicted probability, observed rate, and standard error of the observed rate.
3. Compute the **Brier score** and the **expected calibration error (ECE)** across all bins.
4. Plot a **reliability diagram** (mean predicted vs. observed, with bin counts as point sizes and the diagonal as the perfect-calibration reference). Save to a session-scoped path under `outputs/` or wherever Jon points.
5. Compare against the calibration baseline noted in the most recent modeling ADR, if any.

## Output

- Bin table (mean predicted, observed rate, count, std err) in markdown.
- Brier score and ECE.
- Path to the reliability diagram.
- A verdict: **WELL CALIBRATED** / **NEEDS RECALIBRATION** / **INSUFFICIENT DATA**, with reasoning.
- If recalibration is needed, recommend a method (Platt scaling, isotonic regression, or Bayesian) appropriate to the sample size and the shape of miscalibration.

## References

- `CLAUDE.md` → "Development principles" → "Calibrated probabilities are required"
- The calibration test in `CLAUDE.md` → "Testing requirements" — model training code must include a calibration check on a held-out sample. This command runs the same check on demand.

If no model artifact is yet available (M6 not started), explain this and offer to scaffold the calibration harness as a reusable function instead, so it's ready when M6 begins.
