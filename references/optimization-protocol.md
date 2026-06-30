# Optimization Protocol

This document defines the optimization loop protocol, factor classification
taxonomy, transformation catalog, and stopping criteria for
`skill-factor-optimize` (factor-loop-evolve).

---

## 1. Loop Protocol

```
SETUP:
  1. Set FACTOR_OPTIMIZE_RUN_DIR (auto-timestamped if not set)
  2. Init knowledge base inside output dir
  3. Place initial candidates as candidates.json (5–15 factors)
  4. Validate all candidates → reject invalid ones

FOR iteration = 1 to N:
  5. Backtest validated factors with fixed engine
  6. Diagnose: compute metrics → classify each factor (first-match)
  7. Learn: update knowledge base with lessons
  8. Check stopping criteria → exit if met
  9. Generate next batch: select parents → apply transformations → validate

AFTER all iterations:
  10. Final summary: optimization log, top 5 factors, evolution diagram, config
```

**Stable testing setup**: The backtest engine uses the same universe,
frequency, label definition, and cost assumptions across all iterations
(configurable via `config.json`). This ensures metrics are comparable.

**Parent selection**: Sort all factors by **actual Sharpe** (highest first,
no absolute value). Skip factors whose IC series correlates > 0.7 with an
already-selected parent. Take top N (default 3). All factors with valid Sharpe
are eligible — no classification-based filtering.

---

## 2. Backtest Engine Specification

The backtest engine uses **PandaData API** to fetch real A-share daily OHLCV
data. Credentials are read from a `.env` file in the skill root. PandaData is
mandatory — no synthetic fallback.

All parameters are configured in `config.json` (section `backtest`):

| Parameter       | Default      | Description                              |
| --------------- | ------------ | ---------------------------------------- |
| `indicator`     | "000300"     | Stock universe (000300=CSI 300, 000905=CSI 500) |
| `start_date`    | "20240101"   | Start date (YYYYMMDD)                    |
| `end_date`      | "20251231"   | End date (YYYYMMDD)                      |
| `holding_days`  | 5            | Rebalance interval (trading days)        |
| `n_quantiles`   | 5            | Number of quantile groups                |
| `long_pct`      | 0.2          | Fraction long (top quantile)             |
| `short_pct`     | 0.2          | Fraction short (bottom quantile)         |
| `cost_bps`      | 5.0          | One-way transaction cost (bps)           |
| `lookback_min_days` | 252      | Minimum trading days required per stock  |
| `exclude_st`    | true         | Exclude ST stocks from universe          |

---

## 3. Factor Classification Taxonomy

After backtesting, each factor is classified into exactly one category.
**First match wins**: invalid → overfit → unstable → duplicate → weak → promising.

Sharpe uses **actual value** (not absolute). Lower Sharpe is always worse —
Sharpe 0.1 is worse than Sharpe 0.5, and negative Sharpe means the factor
loses money. IC/ICIR use absolute values.

| Classification | Criteria                                                |
| -------------- | ------------------------------------------------------- |
| **promising**  | Sharpe ≥ 0.3, \|IC\| ≥ 0.01, \|ICIR\| ≥ 0.05, turnover ≤ 0.85, coverage ≥ 0.25 |
| **weak**       | Sharpe in [-0.3, 0.3], \|IC\| < 0.02, \|ICIR\| < 0.3 (catch-all default) |
| **duplicate**  | Spearman rank correlation of IC series > 0.85 with another factor |
| **unstable**   | IC std > 20× \|IC mean\| (high noise-to-signal ratio)    |
| **overfit**    | \|Sharpe\| > 3.0 but \|IC\| < 0.01 (extreme return without predictive power) |
| **invalid**    | Failed backtest, NaN/inf in metrics, coverage < 0.10    |

All thresholds are configurable in `config.json` (section `classification`).

---

## 4. Controlled Transformation Catalog

The variant generator applies **only** these transformations. Each
transformation must have an explicit rationale based on diagnostics.

### 4.1 Parameter Adjustments

| Transformation        | Description                          | Rationale Trigger             |
| --------------------- | ------------------------------------ | ---------------------------- |
| `adjust-lookback`     | Change rolling window n by ±50%      | IC too noisy or too smooth   |
| `adjust-smoothing`    | Add/remove decay_linear or ts_mean   | Turnover too high or too low |
| `adjust-clipping`     | Add/remove clip() or winsorization   | Extreme outlier spikes       |
| `adjust-normalization`| Switch rank/zscore/scale             | Distribution skew issues     |

### 4.2 Structural Transformations

| Transformation        | Description                          | Rationale Trigger             |
| --------------------- | ------------------------------------ | ---------------------------- |
| `combine-factors`     | Arithmetic combination of 2 parents  | Both individually promising, low correlation (< 0.3) |
| `simplify`            | Remove one function/term             | Over-complex, high turnover  |
| `reduce-turnover`     | Increase smoothing or lookback       | Turnover > 0.8               |
| `remove-component`    | Drop one additive/subtractive term   | Weak or noisy component      |

### 4.3 Directional Transformations

| Transformation        | Description                          | Rationale Trigger             |
| --------------------- | ------------------------------------ | ---------------------------- |
| `long-only`           | clip(x, 0, inf)                      | Short side underperforming   |
| `short-only`          | -clip(x, 0, inf)                     | Long side underperforming    |
| `asymmetric`          | Different weights for long vs short  | Asymmetric return profile    |

### 4.4 Prohibited Operations

- **No random mutation** — every change must cite a diagnostic reason.
- **No combining more than 2 parents at once** — keep transformations atomic.
- **No transformations that break the field/function contract.**

---

## 5. Stopping Criteria

The optimization loop stops when **any** of these conditions are met.
All Sharpe comparisons use **actual Sharpe** (not absolute).

| Condition                      | Threshold                          |
| ------------------------------ | ---------------------------------- |
| Max iterations reached         | `max_iterations` (default 5)       |
| Improvement stall              | Best Sharpe unchanged for `stall_iterations` (default 2) consecutive iterations |
| No valid candidates            | All candidates failed validation   |
| Diminishing returns            | Sharpe improvement < `diminishing_return_threshold` (default 0.02) for 2 consecutive iterations |

All thresholds are configurable in `config.json` (section `stopping`).

---

## 6. Experience Memory Structure

The knowledge base stores structured lessons:

```json
{
  "version": 1,
  "iterations_completed": 0,
  "successful_patterns": [
    {
      "pattern": "returns(close, n) / ts_std(returns(close, 1), m)",
      "context": "Risk-adjusted momentum",
      "avg_sharpe": 0.0,
      "times_seen": 0
    }
  ],
  "failed_patterns": [
    {
      "pattern": "log(volume) / delay(log(volume), n)",
      "context": "Volume changes",
      "failure_reason": "",
      "times_failed": 0
    }
  ],
  "field_effectiveness": {
    "close": 0, "volume": 0, "high": 0, "low": 0, "open": 0, "amount": 0
  },
  "error_log": [],
  "high_turnover_structures": [],
  "high_correlation_pairs": [],
  "stability_improvements": [],
  "best_factor_history": []
}
```

---

## 7. Output Directory Structure

All output files live under ``output/<run-id>/``. The knowledge base
(``knowledge_base.json``) lives **inside the output directory**, not at the
skill root. Intermediate files (validated_factors.json, next_candidates.json,
candidates.json) are cleaned after the run.

```
skill-factor-optimize/
├── config.json                      # Hyperparameters (at skill root)
├── .env                             # PandaData credentials (at skill root)
└── output/
    └── <run-id>/                    # One subfolder per run
        ├── backtest_results.json    # Latest iteration backtest
        ├── backtest_results_all.json # All iterations accumulated
        ├── diagnosis.json           # Classification + metrics + suggestions
        ├── knowledge_base.json      # Experience memory
        ├── candidate_evolution.json # Full genealogy tree
        ├── final_summary.json       # Summary report
        ├── evolution_diagram.md     # Mermaid evolution graph
        ├── config.json              # Config snapshot (reproducibility)
        └── trading_data/            # CSV: returns, IC, positions
```

Run directory is set via ``FACTOR_OPTIMIZE_RUN_DIR`` environment variable.
If not set, scripts look for output in the current working directory.
