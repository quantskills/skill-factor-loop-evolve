---
name: factor-loop-evolve
description: >-
  Closed-loop factor evolution system: validate, backtest, diagnose,
  learn, generate variants, repeat for N iterations. Factors evolve
  through controlled transformations toward higher Sharpe. Use when
  iteratively optimizing alpha factors from candidate expressions and
  trading/backtest diagnostics.
license: GPL-3.0-only
quantSkills:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-factor-loop-evolve
  repository_url: https://github.com/quantskills/skill-factor-loop-evolve
  project_type: skill
  collection: factor-optimization
  creator: davideliu
  creator_url: https://github.com/davideliu
  maintainer: davideliu
  maintainer_url: https://github.com/davideliu
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
  rebalance periods. PandaData is the default live-data source; local OHLCV
  CSV input is also supported through `backtest.py --data`.
- A **diagnosis system** — classifies each factor using first-match:
  invalid → overfit → unstable → duplicate → weak → promising.
  All thresholds in `config.json`.
- An **experience memory** — persists lessons about which fields worked,
  which templates failed, which errors recurred, which structures caused
  high turnover, which variants were too correlated, and which refinements
  improved stability.
- A **variant generator** — selects high-quality, diverse parents using a
  parent score where actual Sharpe remains dominant, with small IC/ICIR and
  classification tie-breakers plus turnover/drawdown penalties. By default
  uses **LLM-driven semantic transformations** (configurable via
  `use_llm_transforms`); falls back to 12 hard-coded transformations when
  disabled. LLM-proposed transforms are based on full diagnostic profiles,
  knowledge base insights, and the original user query.
- An **optimization loop coordinator** — manages N iterations, updates
  experience after each iteration, stops when improvement stalls.
- 🆕 **LLM-driven transformation engine** (`scripts/llm_suggest.py`) —
  generates structured prompts for the agent to feed to an LLM, then applies
  the LLM's ranked semantic transform suggestions. Enabled by default
  (`config.json → transformations.use_llm_transforms: true`).
- 🆕 **Active knowledge base** — field diversity boosts reward exploration
  of underexplored fields; failed-pattern penalties avoid repeating mistakes;
  convergence detection warns when the system hits a local optimum.
- 🆕 **Pareto frontier reporting** — multi-objective optimization trade-off
  analysis (Sharpe vs. Turnover vs. Drawdown) identifies non-dominated
  factors optimal for different deployment scenarios.
- A **config system** — all thresholds in `config.json` with `_help`
  documentation. Full config saved with each run for reproducibility.

## Creator, Maintainer, And Scope

- Creator: `davideliu` (`https://github.com/davideliu`).
- Maintainer: `davideliu` for the QuantSkills community.
- Repository: `https://github.com/quantskills/skill-factor-loop-evolve`.
- License: GNU General Public License v3.0 only (`GPL-3.0-only`).
- Scope: Local closed-loop factor research and optimization from OHLCV data.
  Uses PandaData API for real A-share market data by default (credentials from
  ``.env``), or a local OHLCV CSV supplied with `backtest.py --data`.
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
   Uses PandaData API (CSI 300, 2024-2025 by default), unless `--data <ohlcv.csv>`
   is supplied. Configurable via `config.json`.
6. **Diagnose** — `python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json`
   Classifies each factor. Output is flattened: `sharpe`, `annual_return`,
   `max_drawdown`, `ic_mean`, `ic_std`, `icir`, `turnover`, `coverage`,
   `long_return`, and `short_return` are directly on each diagnostic entry.
7. **Learn** — `python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json`
   Updates experience memory with successful patterns and lessons.
8. **Check stopping** — if Sharpe unchanged for 2 iterations or max iterations reached, go to step 10.
9. **Generate next batch** — `python scripts/generate_candidates.py ...`
   Parent selection: ranks valid, non-invalid factors by parent score; actual
   Sharpe dominates, while IC/ICIR, classification, turnover, drawdown,
   active-KB diversity boosts, and pairwise IC correlation are used as
   tie-breakers and risk controls. Defaults: choose up to 3 parents, keep at
   least 2 when available.
   **By default, uses LLM-driven semantic transforms**. First run
   `llm_suggest.py --generate-prompt`, feed the prompt to an LLM, apply the
   response into `transform_suggestions.json`, then run `generate_candidates.py`.
   The suggestion file keeps all iterations in `suggestion_history[]`; each
   entry and suggestion records the completed diagnosis iteration it refers to
   and the next candidate iteration it targets.
   Controlled by `transformations.use_llm_transforms` in `config.json`
   (`true` = LLM priority, `false` = static transforms only).
   Override with `--use-llm` (force LLM), `--no-llm` (force static), or `--no-active-kb` (disable diversity boosts).
   Then validate and go to step 5.
10. **Final report** — `python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json`
    Produces concise report + evolution diagram + copies config.json.

## Output Contract

All files live inside ``output/<run-id>/``. Intermediate files are cleaned
after the run. The skill root stays clean (only `config.json` and `.env`).

**Final output (8–10 files + trading_data):**

| File | Content |
|------|---------|
| `backtest_results_all.json` | All iterations accumulated (``iterations[]`` array) — single source of truth |
| `diagnosis.json` | Classification + key metrics (S, IC, TO) + suggestions (flattened) |
| `knowledge_base.json` | Experience memory: successful patterns, error log, field effectiveness |
| `candidate_evolution.json` | Full genealogy tree with per-node metrics |
| `final_summary.json` | Optimization log, top 5 factors, Pareto frontier, worth_keeping, original query, active config, evolution diagram |
| `config.json` | Full config used for this run (reproducibility) |
| `evolution_diagram.md` | Mermaid graph + original query + top-10 table + Pareto frontier (open with Cmd+Shift+V) |
| `transform_suggestions.json` | 🆕 LLM-suggested transforms with all iteration history (kept if LLM enabled) |
| `trading_data/` | CSV: portfolio returns, IC series, positions |

`transform_prompt.md` and `llm_response.json` are intermediate and cleaned after the run.

No `validated_factors.json` or `validated_factors_passed.json` or
`next_candidates.json` in final output — these are intermediate and cleaned.

### How to Interpret Results (for agents)

Read `final_summary.json` first for the high-level picture:

- **`optimization_log`**: list of `{iteration, best_factor, best_sharpe}` per iteration.
  Sharpe trending up = evolution working. Flat = hit ceiling for current config.
- **`best_factors`**: top 5 factors sorted by actual Sharpe. Each has `name`, `sharpe`,
  `ic_mean`, `turnover`, `annual_return`, `expression`, `classification`.
- **`worth_keeping`**: `true` if best Sharpe ≥ `worth_keeping_sharpe_threshold` (default 0.3).
- **`query`**: the original user input query that initiated this factor evolution run.
- **`pareto_frontier`**: 🆕 non-dominated factors across Sharpe, turnover, and drawdown — each optimal in at least one trade-off dimension.
- **`evolution_diagram`**: raw Mermaid string rendered in `evolution_diagram.md`.
- **`active_config`**: full config snapshot for reproducibility.

For detail, read `diagnosis.json`:
- `diagnostics[]`: per-factor entry with `name`, `expression`, `classification`,
  flattened performance/risk metrics, `diagnosis_notes`, and
  `improvement_suggestions`.
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

Eligible parents must have a numeric Sharpe and must not be classified as
`invalid`.

The selector computes `_parent_score`:

- Actual Sharpe is the dominant base score.
- Active knowledge-base boosts can adjust the base for field diversity and
  repeated failed-pattern avoidance.
- Small bonuses reward `promising` classification, stronger absolute IC, and
  stronger absolute ICIR.
- Penalties reduce priority for high turnover, deep drawdown, `unstable`,
  `duplicate`, or `overfit` classifications.

The selector then chooses a diverse parent set:

- Prefer pairwise absolute IC correlation ≤ `duplicate_correlation_threshold`
  (default 0.7).
- Return up to `max_parents` (default 3).
- Preserve at least `min_parents` (default 2) when enough candidates exist by
  relaxing the threshold to 0.85 then 0.95.
- Only add a highly correlated parent as a last resort to satisfy
  `min_parents`.

The same selector is used by `llm_suggest.py` when building the LLM prompt and
by `generate_candidates.py` when creating the next batch.

## Transformation Reference

The 12 controlled transformations and the rationale behind each:

| Transformation | Rationale |
|---------------|-----------|
| `flip-sign` | Negative Sharpe — inverting recovers a positive Sharpe from a directionally-wrong factor |
| `reduce-turnover` | Turnover > 0.8 — smoothing reduces excessive trading and transaction costs |
| `adjust-lookback` | IC signal too noisy or too smooth — changing lookback window can improve stability |
| `adjust-smoothing` | Turnover extreme — adjusting smoothing balances signal decay speed vs. trading cost |
| `adjust-clipping` | Extreme outliers distort the signal — clipping caps their influence for more robust rankings |
| `adjust-normalization` | Distribution skewed — switching normalization improves cross-sectional comparability |
| `combine-factors` | Both promising with low correlation — combining diversifies the alpha source |
| `simplify` | Expression over-complex — removing nesting reduces overfit risk |
| `remove-component` | Sub-component is weak — removing it purifies the remaining signal |
| `long-only` | Short leg underperforming — keeping only longs eliminates dead-weight shorts |
| `short-only` | Long leg underperforming — keeping only shorts eliminates dead-weight longs |
| `asymmetric` | Long/short returns asymmetric — weighting captures the stronger side more heavily |

`flip-sign` is applied **first** (before other transforms) so negative-Sharpe
factors can become positive before further refinement.
5 transformations per parent (fixed).

In static mode, `combine-factors` is applied as a **fallback** when fewer than
`max_candidates` candidates are generated from per-parent transforms; it merges
two low-correlation parents. LLM mode uses only LLM-proposed transforms.
`remove-component` is not yet implemented (always returns None).

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
# 🆕 LLM-driven transformations are the DEFAULT (config: use_llm_transforms=true)
# Auto-detects transform_suggestions.json. If missing, generate_candidates.py
# writes transform_prompt.md and stops; use --no-llm only for intentional static fallback.

# LLM pipeline (default):
python scripts/llm_suggest.py --generate-prompt --diagnosis diagnosis.json --knowledge knowledge_base.json --query "$USER_QUERY" --output transform_prompt.md
# Feed transform_prompt.md to LLM → save response as llm_response.json
python scripts/llm_suggest.py --apply-response --response llm_response.json --diagnosis diagnosis.json --output transform_suggestions.json
python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json --query "$USER_QUERY"

# Force static (hard-coded) transforms only:
python scripts/generate_candidates.py ... --no-llm

# 🆕 Disable active KB if desired:
python scripts/generate_candidates.py ... --no-active-kb

# After last iteration — final summary → final_summary.json + evolution_diagram.md + config.json
python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json
```

Use full paths under ``FACTOR_OPTIMIZE_RUN_DIR`` for explicit ``--output`` and
input arguments, or omit ``--output`` to let scripts write to the run directory.
Bare filenames are resolved relative to the current working directory.
``FACTOR_OPTIMIZE_RUN_DIR`` must be set for pipeline continuity across script calls.

## Execution Details For Agents

### Run Directory Discipline

Set one run directory and pass full paths between scripts:

```bash
export FACTOR_OPTIMIZE_RUN_DIR="output/run_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$FACTOR_OPTIMIZE_RUN_DIR"
```

Bare filenames are resolved from the current working directory. For reliable
multi-script runs, use paths under `$FACTOR_OPTIMIZE_RUN_DIR`.

### LLM Priority

`generate_candidates.py` defaults to LLM mode when
`config.json -> transformations.use_llm_transforms` is true.

If `transform_suggestions.json` is missing, `generate_candidates.py` writes
`transform_prompt.md` and exits with status `2`. Complete the LLM step, then
run `generate_candidates.py` again.

`transform_suggestions.json` uses this history shape:

```json
{
  "version": 2,
  "latest_iteration": 3,
  "latest_suggestions": [],
  "suggestion_history": [
    {
      "iteration": 3,
      "refers_to": {
        "diagnosis_iteration": 3,
        "candidate_iteration": 4
      },
      "n_suggestions": 0,
      "suggestions": []
    }
  ]
}
```

Each suggestion also has `source_iteration`, `target_iteration`, and
`refers_to`. `generate_candidates.py` reads `latest_suggestions` and still
accepts the old list-only format for older runs.

Use static transforms only when the user explicitly asks for static mode:

```bash
python scripts/generate_candidates.py ... --no-llm
```

### Local CSV Backtest

For offline fixtures:

```bash
python scripts/backtest.py \
  --factors "$FACTOR_OPTIMIZE_RUN_DIR/validated_factors_passed.json" \
  --data /path/to/ohlcv.csv \
  --output "$FACTOR_OPTIMIZE_RUN_DIR/backtest_results_all.json"
```

The CSV must contain:

```text
date,symbol,open,high,low,close,volume,amount
```

### Output Reading Order

1. `final_summary.json`
2. `evolution_diagram.md`
3. `diagnosis.json`
4. `backtest_results_all.json`
5. `knowledge_base.json`

Intermediate files such as `validated_factors_passed.json`,
`next_candidates.json`, `transform_prompt.md`, and `llm_response.json` are
cleaned by the final summary step.

### Verification After Code Changes

```bash
python3 -m py_compile scripts/*.py
git diff --check
```

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
6. Generate LLM suggestions first, then candidates:
   python scripts/llm_suggest.py --generate-prompt --diagnosis diagnosis.json --knowledge knowledge_base.json --query "$USER_QUERY" --output transform_prompt.md
   Feed transform_prompt.md to LLM and save JSON as llm_response.json.
   python scripts/llm_suggest.py --apply-response --response llm_response.json --diagnosis diagnosis.json --output transform_suggestions.json
   python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json
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
- `scripts/backtest.py` — backtest engine using PandaData API by default, or a
  local OHLCV CSV via `--data`.
- `scripts/diagnose.py` — factor diagnosis and classification.
- `scripts/knowledge_base.py` — experience memory management.
- `scripts/generate_candidates.py` — controlled variant generation.
- `scripts/optimizer.py` — optimization loop coordinator.
