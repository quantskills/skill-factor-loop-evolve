# Factor Expression Field & Function Contract

This document defines the exact contract for alpha factor expressions generated
by `skill-factor-loop-evolve`. All generated or optimized expressions **must** use
only the fields and functions listed below.

---

## 1. Available Field Variables

Each field is a `date × symbol` DataFrame (OHLCV market data):

| Field    | Description              |
| -------- | ------------------------ |
| `open`   | Daily open price         |
| `high`   | Daily high price         |
| `low`    | Daily low price          |
| `close`  | Daily close price        |
| `volume` | Daily trading volume     |
| `amount` | Daily trading amount     |

> ⚠️ **Only these 6 fields exist.** Do NOT use `vwap`, `adjfactor`, `turnover`,
> `market_cap`, or any other field unless explicitly listed above.

---

## 2. Available Functions

### 2.1 Cross-Sectional (per date)

| Function          | Description                                    |
| ----------------- | ---------------------------------------------- |
| `rank(x)`         | Cross-sectional percentile rank at each date (0–1) |
| `zscore(x)`       | Cross-sectional z-score at each date           |
| `scale(x, a=1)`   | Cross-sectional rescaling so |sum| == a       |

### 2.2 Time-Series Rolling

| Function                | Description                                          |
| ----------------------- | ---------------------------------------------------- |
| `ts_rank(x, n)`         | Time-series percentile rank over n periods           |
| `ts_zscore(x, n)`       | Rolling z-score over n periods                       |
| `ts_mean(x, n)`         | Rolling mean                                         |
| `ts_std(x, n)`          | Rolling standard deviation                           |
| `ts_max(x, n)`          | Rolling maximum                                      |
| `ts_min(x, n)`          | Rolling minimum                                      |
| `ts_sum(x, n)`          | Rolling sum                                          |
| `ts_argmax(x, n)`       | Periods since rolling maximum within the last n bars |
| `ts_argmin(x, n)`       | Periods since rolling minimum within the last n bars |
| `correlation(x, y, n)`  | Rolling Pearson correlation per symbol               |
| `covariance(x, y, n)`   | Rolling covariance per symbol                        |
| `decay_linear(x, n)`    | Linearly-decayed weighted moving average             |

### 2.3 Lag / Difference / Returns

| Function        | Description                              |
| --------------- | ---------------------------------------- |
| `delay(x, n)`   | Lag x by n periods                       |
| `delta(x, n)`   | x - delay(x, n)                          |
| `returns(x, n)` | Percentage change over n periods (default n=1) |
| `adv(n)`        | Rolling mean of volume over n periods    |

### 2.4 Element-wise Math

| Function                    | Description                       |
| --------------------------- | --------------------------------- |
| `sign(x)`                   | Element-wise sign (-1, 0, 1)      |
| `log(x)`                    | Natural logarithm                 |
| `abs(x)`                    | Absolute value                    |
| `power(x, n)`               | x raised to power n               |
| `signed_power(x, n)`        | sign(x) * |x|^n                  |
| `min(x, y)`                 | Element-wise minimum              |
| `max(x, y)`                 | Element-wise maximum              |
| `clip(x, lower, upper)`     | Clip values to [lower, upper]     |

### 2.5 Arithmetic

Standard arithmetic operators: `+`, `-`, `*`, `/` between DataFrames and scalars.

---

## 3. Look-Ahead Bias Prevention

- `delay(x, n)`, `delta(x, n)`, and `returns(x, n)` MUST use `n ≥ 1`.
  Using `n ≤ 0` peeks into the future → **REJECTED**.
- All rolling functions (`ts_*`, `correlation`, `covariance`, `decay_linear`)
  inherently use only past data — this is correct.
- Cross-sectional functions (`rank`, `zscore`, `scale`) operate within each
  date independently — no look-ahead.

---

## 4. Numerical Stability Rules

- **No division by zero**: use `max(denom, 1e-8)` as guard.
- **No log of non-positive**: use `log(max(x, 1e-8))`.
- **Prefer rank/zscore-based expressions** — they are naturally stable.
- **Avoid extreme power values** — `power(x, n)` with |n| > 5 is warned.
- **Avoid division of very small numbers** — produces extreme outliers.

---

## 5. Factor Specification Format

Every factor must be represented as a JSON object with these fields:

| Field          | Type   | Required | Description                                     |
| -------------- | ------ | -------- | ----------------------------------------------- |
| `name`         | string | Yes      | Unique factor name (snake_case)                 |
| `expression`   | string | Yes      | The factor formula using allowed fields/functions |
| `description`  | string | Yes      | Human-readable description                      |
| `rationale`    | string | Yes      | Economic or statistical rationale               |
| `generation`   | string | Yes      | How this factor was created (initial/manual/variant-*) |
| `parent`       | string | No       | Name of parent factor (for variants)            |
| `transformation` | string | No     | Description of transformation applied           |

---

## 6. Complexity Limits

- Expression length: ≤ 500 characters.
- Function nesting depth: ≤ 5 levels.
- Number of distinct function calls: ≤ 15.
- Rolling window parameter `n`: between 2 and 252 (trading days).
- Expressions exceeding these limits receive a **complexity warning** but are
  not automatically rejected.
