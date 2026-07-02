# Optimization Protocol

This document defines the optimization loop protocol, factor classification
taxonomy, transformation catalog, and stopping criteria for
`skill-factor-loop-evolve`.

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

**Parent selection**: Select valid, non-invalid factors by `_parent_score`.
Actual Sharpe remains the dominant signal. IC/ICIR, classification, turnover,
drawdown, and active knowledge-base diversity are tie-breakers. Prefer parents
whose absolute pairwise IC-series correlation is ≤ 0.7. Select up to 3 parents
by default, but only relax correlation thresholds enough to preserve the
minimum parent count (default 2).

---

## 2. Backtest Engine Specification

The backtest engine uses **PandaData API** to fetch real A-share daily OHLCV
data. Credentials are read from a `.env` file in the skill root. PandaData is
the default live-data path. A local OHLCV CSV can be supplied with
`backtest.py --data` for offline or fixture-based runs.

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

| Transformation        | Rationale |
| --------------------- | --------- |
| `adjust-lookback`     | IC signal too noisy or too smooth — changing lookback window can improve stability |
| `adjust-smoothing`    | Turnover extreme — adjusting smoothing balances signal decay speed vs. trading cost |
| `adjust-clipping`     | Extreme outliers distort the signal — clipping caps their influence for more robust rankings |
| `adjust-normalization`| Distribution skewed — switching normalization improves cross-sectional comparability |

### 4.2 Structural Transformations

| Transformation        | Rationale |
| --------------------- | --------- |
| `combine-factors`     | Both promising with low correlation — combining diversifies the alpha source |
| `simplify`            | Expression over-complex — removing nesting reduces overfit risk |
| `reduce-turnover`     | Turnover > 0.8 — smoothing reduces excessive trading and transaction costs |
| `remove-component`    | Sub-component is weak — removing it purifies the remaining signal |

### 4.3 Directional Transformations

| Transformation        | Rationale |
| --------------------- | --------- |
| `long-only`           | Short leg underperforming — keeping only longs eliminates dead-weight shorts |
| `short-only`          | Long leg underperforming — keeping only shorts eliminates dead-weight longs |
| `asymmetric`          | Long/short returns asymmetric — weighting captures the stronger side more heavily |

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
skill-factor-loop-evolve/
├── config.json                      # Hyperparameters (at skill root)
├── .env                             # PandaData credentials (at skill root)
└── output/
    └── <run-id>/                    # One subfolder per run
        ├── backtest_results_all.json # All iterations accumulated (single source of truth)
        ├── diagnosis.json           # Classification + metrics + suggestions
        ├── knowledge_base.json      # Experience memory
        ├── candidate_evolution.json # Full genealogy tree
        ├── transform_suggestions.json # LLM transforms with per-iteration history
        ├── final_summary.json       # Summary report
        ├── evolution_diagram.md     # Mermaid evolution graph
        ├── config.json              # Config snapshot (reproducibility)
        └── trading_data/            # CSV: returns, IC, positions
```

Run directory is set via ``FACTOR_OPTIMIZE_RUN_DIR`` environment variable.
If not set, scripts look for output in the current working directory.

``transform_suggestions.json`` is appendable. It stores
``suggestion_history[]`` for all applied LLM response iterations, plus
``latest_suggestions`` for the next candidate-generation call. Every history
entry and suggestion records ``diagnosis_iteration`` and
``candidate_iteration`` under ``refers_to``.
