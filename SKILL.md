---
name: factor-loop-evolve
description: >-
  Closed-loop factor evolution system: validate, backtest, diagnose,
  learn, generate variants, repeat for N iterations. Factors evolve
  through controlled transformations toward higher Sharpe.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: factor-loop-evolve
  repository_url: https://github.com/quantskills/factor-loop-evolve
  project_type: skill
  collection: factor-optimization
  creator: davideliu
  creator_url: https://github.com/davideliu
  maintainer: davideliu
  maintainer_url: https://github.com/davideliu
quantSkills:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: factor-loop-evolve
  repository_url: https://github.com/quantskills/factor-loop-evolve
  project_type: skill
  collection: factor-optimization
  category: factor
  tags:
    - factor-optimization
    - closed-loop
    - backtest
    - factor-validation
    - experience-memory
    - iterative-improvement
    - alpha-discovery
    - factor-diagnosis
    - self-improving
    - genetic-optimization
  platforms:
    - claude-code
    - codex
    - cursor
    - openclaw
  language: zh-en
  status: draft
  validation_level: listed
  maintainer_type: community
  requires:
    - skill-pandadata-api
  summary_zh: "本地闭环因子研究系统：生成导入因子，验证，回测（PandaData真实A股数据），诊断，优化，经验记忆，生成新批次，迭代N轮，实现自我改进的因子发现与优化。"
  summary_en: "Local closed-loop factor research: generate, validate, backtest, diagnose, learn, iterate N rounds. Self-improving alpha discovery and optimization."
---

# Factor Loop Evolve

Use this skill to run a **closed-loop factor evolution pipeline**.
You (the agent) coordinate iterative cycles of factor generation, validation,
backtesting, diagnosis, experience accumulation, and controlled variant
generation. The skill requires **panda_data** (pip install) and PandaData
credentials in ``.env`` for real A-share market data.

This skill provides:

- A **factor contract** — allowed fields, functions, and expression rules
  that every candidate must follow.
- A **toy-data validator** — catches syntax errors, unsupported fields,
  look-ahead bias, and numerical instability before any backtest.
- A **real-data backtest engine** — consistent cross-sectional long-short
  backtest powered by **PandaData API** with real A-share OHLCV data over
  a customizable period (CSI 300 default, configurable). Rebalances at
  configurable intervals, goes long top quintile and short bottom quintile.
  Forward returns are computed from the rebalance date with **no look-ahead
  bias**. Turnover is measured from actual position changes between
  rebalance periods. **PandaData is required**.
- A **diagnosis system** — classifies each factor using first-match:
  invalid → overfit → unstable → duplicate → weak → promising.
  All thresholds in `config.json`.
- An **experience memory** — persists lessons about which fields worked,
  which templates failed, which errors recurred, which structures caused
  high turnover, which variants were too correlated, and which refinements
  improved stability.
- A **variant generator** — selects the strongest current factors as parents
  by **actual Sharpe** (highest first, no abs). Applies 12 controlled
  transformations including `flip-sign` for negative Sharpe factors,
  `reduce-turnover` for high turnover, and `adjust-lookback`/`smoothing`/
  `clipping`/`normalization` with explicit rationale.
- An **optimization loop coordinator** — manages N iterations, updates
  experience after each iteration, stops when improvement stalls.
- A **config system** — all thresholds in `config.json` with `_help`
  documentation. Full config saved with each run for reproducibility.

## Creator, Maintainer, And Scope

- Creator: `davideliu` (`https://github.com/davideliu`).
- Maintainer: `davideliu` for the QuantSkills community.
- Repository: `https://github.com/quantskills/skill-factor-optimize`.
- License: GNU General Public License v3.0 only (`GPL-3.0-only`).
- Scope: Local closed-loop factor research and optimization from OHLCV data.
  Uses PandaData API for real A-share market data (credentials from ``.env``).
  PandaData is mandatory — the skill does not use synthetic fallback data.
  The skill is not official investment advice, a certified data product, or
  a guarantee of trading performance.

## Core Workflow

### Setup

1. **Place initial candidates** — `candidates.json` in the run output folder
   with 5–15 factor expressions (name, expression, description, rationale, generation).
2. **Verify config** — `config.json` at skill root defines all thresholds.
   Scripts fall back to hardcoded defaults if missing.
3. **Set PandaData credentials** — in `.env` at skill root.

### Iteration 0: Validate

4. **Validate** — `python scripts/validator.py --factors <candidates.json>`
   Produces `validated_factors_passed.json` in the output folder.

### Iteration 1..N: Optimize Loop

5. **Run backtest** — `python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json`
   Uses PandaData API (CSI 300, 2024-2025 by default). Configurable via `config.json`.
6. **Diagnose** — `python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json`
   Classifies each factor. Output is flattened (sharpe, ic_mean, turnover directly, no nested metrics dict).
7. **Learn** — `python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json`
   Updates experience memory with successful patterns and lessons.
8. **Check stopping** — if Sharpe unchanged for 2 iterations or max iterations reached, go to step 10.
9. **Generate next batch** — `python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json`
   Parent selection: sorts by actual Sharpe (highest first), skips correlated duplicates (>0.7), takes top N.
   Applies up to 5 transformations per parent. Then validate and go to step 5.
10. **Final report** — `python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json`
    Produces concise report + evolution diagram + copies config.json.

## Output Contract

All files live inside ``output/<run-id>/``. Intermediate files are cleaned
after the run. The skill root stays clean (only `config.json` and `.env`).

**Final output (8 files + trading_data):**

| File | Content |
|------|---------|
| `backtest_results_all.json` | All iterations accumulated (``iterations[]`` array) — single source of truth |
| `diagnosis.json` | Classification + key metrics (S, IC, TO) + suggestions (flattened) |
| `knowledge_base.json` | Experience memory: successful patterns, error log, field effectiveness |
| `candidate_evolution.json` | Full genealogy tree with per-node metrics |
| `final_summary.json` | Optimization log, top 5 factors, worth_keeping, active config, evolution diagram |
| `config.json` | Full config used for this run (reproducibility) |
| `evolution_diagram.md` | Mermaid graph + top-10 filtered table (open with Cmd+Shift+V) |
| `trading_data/` | CSV: portfolio returns, IC series, positions |

No `validated_factors.json` or `validated_factors_passed.json` or
`next_candidates.json` in final output — these are intermediate and cleaned.

### How to Interpret Results (for agents)

Read `final_summary.json` first for the high-level picture:

- **`optimization_log`**: list of `{iteration, best_factor, best_sharpe}` per iteration.
  Sharpe trending up = evolution working. Flat = hit ceiling for current config.
- **`best_factors`**: top 5 factors sorted by actual Sharpe. Each has `name`, `sharpe`,
  `ic_mean`, `turnover`, `annual_return`, `expression`, `classification`.
- **`worth_keeping`**: `true` if best Sharpe ≥ `worth_keeping_sharpe_threshold` (default 0.3).
- **`evolution_diagram`**: raw Mermaid string rendered in `evolution_diagram.md`.
- **`active_config`**: full config snapshot for reproducibility.

For detail, read `diagnosis.json`:
- `diagnostics[]`: per-factor entry with `name`, `expression`, `classification`,
  `sharpe`, `ic_mean`, `turnover`, `diagnosis_notes`, `improvement_suggestions`.
- `best_factor`, `best_sharpe`: best of this iteration.
- `n_promising`, `n_weak`, etc.: classification counts.
- `correlations`: pairwise IC correlations between factors.
\nFor full metrics per factor, read `backtest_results_all.json` — it has `annual_return`,
`max_drawdown`, `coverage`, `ic_std`, `icir`, `long_return`, `short_return`, and
`_trading_data` with IC series and portfolio returns.

For cross-iteration trend, read `backtest_results_all.json`:
- `iterations[]`: each entry has `iteration` number and `results[]` with per-factor
  metrics from that iteration's backtest.

### Evolution Diagram Tags

| Tag | Threshold | Meaning |
|-----|-----------|---------|
| 🟢 high Sharpe | S ≥ 0.5 | Strong positive risk-adjusted return |
| 🔴 low Sharpe | S < 0.2 | Weak or negative Sharpe |
| 🟢 high IC | \|IC\| ≥ 0.02 | Strong cross-sectional predictive power |
| 🔴 low IC | \|IC\| < 0.01 | Weak predictive power |
| 🔴 high turnover | TO > 0.85 | High trading cost |
| 🔴 high drawdown | DD < −50% | Deep peak-to-trough decline |
| 🟢 positive return | AR > 0 | Positive annualized return |

### Parent Selection Rule

Sort by actual Sharpe (highest first), skip correlated duplicates (>0.7),
take top N (default 3). No classification filtering — ALL factors with
valid Sharpe are eligible.

## Transformation Reference

The 12 controlled transformations, their triggers, and rationale:

| Transformation | Trigger | Effect | Rationale |
|---------------|---------|--------|-----------|
| `flip-sign` | Sharpe < −0.3 | Negate whole expression | Negative Sharpe → flip yields positive |
| `reduce-turnover` | Turnover > 0.8 | Wrap in `ts_mean()` | High turnover → smooth signal |
| `adjust-lookback` | Turnover < 0.3 or noisy IC | Adjust window ±30–50% | Too stable → change sensitivity |
| `adjust-smoothing` | Extreme turnover | Change decay/smoothing | Optimize signal decay speed |
| `adjust-clipping` | Extreme outliers | Add/adjust sigma clipping | Outliers → cap extremes |
| `adjust-normalization` | Distribution skew | Switch norm (zscore/rank/min-max) | Skew → improve statistical properties |
| `combine-factors` | Both promising, low corr | Weighted merge of two | Complementary → combine |
| `simplify` | Over-complex expression | Remove redundant nesting | Complex → reduce overfit risk |
| `remove-component` | Weak/noisy component | Drop weak sub-expression | Noise → purify signal |
| `long-only` | Short side underperforming | Zero out short leg | Short dead weight → long only |
| `short-only` | Long side underperforming | Zero out long leg | Long dead weight → short only |
| `asymmetric` | Asymmetric long/short returns | Different weights per side | Asymmetry → optimize ratio |

`flip-sign` is applied **first** (before other transforms) so negative-Sharpe
factors can become positive before further refinement. Up to
`max_transforms_per_parent` (default 5) transforms per parent.

`combine-factors` is applied as a **fallback** when fewer than
`max_candidates` candidates are generated from per-parent transforms — it
merges two low-correlation parents. `remove-component` is not yet implemented
(always returns None). The other 10 transforms all work, though `simplify`
(requires >3 nesting levels), `long-only`, `short-only`, and `asymmetric`
(require no existing `clip()`) only trigger under specific conditions.

## Calling Pattern

```bash
# Set run directory (auto-generated if not set)
export FACTOR_OPTIMIZE_RUN_DIR="output/run_$(date +%Y%m%d_%H%M%S)"

# Initialize knowledge base inside output
python scripts/knowledge_base.py --init --output "$FACTOR_OPTIMIZE_RUN_DIR/knowledge_base.json"

# Validate candidates → validated_factors_passed.json (intermediate, cleaned later)
python scripts/validator.py --factors candidates.json

# Backtest → backtest_results_all.json (all iterations accumulated)
python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json

# Diagnose → diagnosis.json
python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json

# Learn from diagnosis
python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json

# Generate next candidates → next_candidates.json (intermediate)
python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json

# After last iteration — final summary → final_summary.json + evolution_diagram.md + config.json
python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json
```

All paths are relative to the output run directory. ``FACTOR_OPTIMIZE_RUN_DIR``
must be set for pipeline continuity across script calls.

## Agent Prompt Template

When the user asks to optimize factors, use this prompt:

```
You are a quantitative researcher running a closed-loop factor evolution
pipeline (factor-loop-evolve). You will iterate for {N} rounds.

## Setup
1. Read config.json for current hyperparameters.
2. Read references/factor-contract.md for allowed fields and functions.
3. Place initial candidates as candidates.json in the output directory.
4. Set FACTOR_OPTIMIZE_RUN_DIR and init knowledge base:
   python scripts/knowledge_base.py --init --output $FACTOR_OPTIMIZE_RUN_DIR/knowledge_base.json

## For Each Iteration
1. Validate: python scripts/validator.py --factors <candidates.json>
2. Backtest: python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json
3. Diagnose: python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json
4. Learn: python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json
5. Check stopping: if best Sharpe unchanged for {stall} iterations or {max} iterations reached → stop
6. Generate: python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json
   Then validate next_candidates.json for the next loop.

## After All Iterations
7. python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json
8. Read final_summary.json and report:
   - Optimization log (Sharpe progression across iterations)
   - Top 5 best factors (name, Sharpe, IC, turnover, expression)
   - Whether worth keeping
   - Key patterns from knowledge_base.json (field_effectiveness, successful_patterns)
   - Preview evolution_diagram.md
```

## Cross-Agent Use

- Claude Code / Codex: load via `SKILL.md`.
- Cursor: use `agents/cursor-rule.mdc`.
- Hermes / OpenClaw: use `agents/portable-loader.md`.
- OpenAI-style: read `agents/openai.yaml`.

## Example Run: Momentum Factor Evolution on CSI 300

This is a **concrete, copy-pasteable** example showing a full 3-iteration
run evolving momentum factors.

### User Request

```
帮我优化动量因子，跑3轮迭代。从经典的动量公式出发，每轮诊断后自动生成改进变体。
```

### Quick Run Script

```bash
cd skill-factor-optimize
export FACTOR_OPTIMIZE_RUN_DIR="output/run_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$FACTOR_OPTIMIZE_RUN_DIR"

# Embedded candidates (sample momentum factors)
python -c "
import json
candidates = [
    {'name':'simple_mom_5d','expression':'returns(close,5)','description':'5-day momentum','rationale':'Short-term trend','generation':'initial'},
    {'name':'simple_mom_20d','expression':'returns(close,20)','description':'20-day momentum','rationale':'Medium-term trend','generation':'initial'},
    {'name':'risk_adj_mom_10d','expression':'returns(close,10)/max(ts_std(returns(close,1),20),1e-8)','description':'Risk-adj 10d','rationale':'Risk-adjusted','generation':'initial'},
]
with open('$FACTOR_OPTIMIZE_RUN_DIR/candidates.json','w') as f: json.dump(candidates, f)
"

KB="$FACTOR_OPTIMIZE_RUN_DIR/knowledge_base.json"
python scripts/knowledge_base.py --init --output "$KB"
python scripts/validator.py --factors "$FACTOR_OPTIMIZE_RUN_DIR/candidates.json"

for it in 1 2 3; do
    python scripts/backtest.py --factors "$FACTOR_OPTIMIZE_RUN_DIR/validated_factors_passed.json" \
        --output "$FACTOR_OPTIMIZE_RUN_DIR/backtest_results_all.json"
    python scripts/diagnose.py --results "$FACTOR_OPTIMIZE_RUN_DIR/backtest_results_all.json" \
        --factors "$FACTOR_OPTIMIZE_RUN_DIR/validated_factors_passed.json" \
        --output "$FACTOR_OPTIMIZE_RUN_DIR/diagnosis.json"
    python scripts/knowledge_base.py --learn "$FACTOR_OPTIMIZE_RUN_DIR/diagnosis.json" --knowledge "$KB"
    if [ $it -lt 3 ]; then
        python scripts/generate_candidates.py --diagnosis "$FACTOR_OPTIMIZE_RUN_DIR/diagnosis.json" \
            --knowledge "$KB" --output "$FACTOR_OPTIMIZE_RUN_DIR/next_candidates.json"
        python scripts/validator.py --factors "$FACTOR_OPTIMIZE_RUN_DIR/next_candidates.json"
    fi
done

python scripts/optimizer.py --summary --knowledge "$KB" --output "$FACTOR_OPTIMIZE_RUN_DIR/final_summary.json"
```

### Expected Timeline

| Phase | Approx. Time |
|-------|--------------|
| Validation | < 1 second |
| Backtest (PandaData, 300 stocks × 2 years) | 30–120 seconds per iteration |
| Diagnosis + Learn + Generate | < 5 seconds per iteration |
| **Total for 3 iterations** | **~5 minutes** |

### Reading the Results

```bash
# View Sharpe progression
python -c "
import json
fs = json.load(open('$FACTOR_OPTIMIZE_RUN_DIR/final_summary.json'))
for l in fs['optimization_log']:
    print(f\"Iter {l['iteration']}: {l['best_sharpe']:.2f} ({l['best_factor']})\")
"

# View top factors
python -c "
import json
fs = json.load(open('$FACTOR_OPTIMIZE_RUN_DIR/final_summary.json'))
for f in fs['best_factors']:
    print(f\"{f['name']}: S={f['sharpe']:.2f} IC={f['ic_mean']:.3f} TO={f['turnover']:.2f}\")
"

# Check if worth keeping
python -c "
import json
print(json.load(open('$FACTOR_OPTIMIZE_RUN_DIR/final_summary.json'))['worth_keeping'])
"
```

## Setup

Create a `.env` file in the skill root with PandaData credentials:

```bash
PANDA_AI_USERNAME="your_username"
PANDA_AI_PASSWORD="your_password"
PANDA_AI_BASE_URL="http://pandadata.pandaaiquant.com"
```

Install dependencies:

```bash
pip install -r requirements.txt
# Or install panda_data wheel directly:
pip install panda_data/panda_data-0.1.0-py3-none-any.whl
```

## Reference Files

- `references/factor-contract.md` — allowed fields, functions, and expression rules.
- `references/optimization-protocol.md` — loop protocol, classification taxonomy, stopping criteria.
- `references/agent-integration.md` — multi-agent install and smoke test.
- `scripts/contracts.py` — shared contract definitions (single source of truth).
- `scripts/validator.py` — toy-data validator with look-ahead bias and stability checks.
- `scripts/backtest.py` — backtest engine powered by PandaData API (real A-share data).
- `scripts/diagnose.py` — factor diagnosis and classification.
- `scripts/knowledge_base.py` — experience memory management.
- `scripts/generate_candidates.py` — controlled variant generation.
- `scripts/optimizer.py` — optimization loop coordinator.
