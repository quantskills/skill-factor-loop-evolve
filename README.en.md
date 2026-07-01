# Factor Loop Evolve

**English** | [简体中文](README.md)

> Local closed-loop factor evolution system: validate → backtest → diagnose → learn → generate variants → iterate. Self-improving factor discovery powered by PandaData real A-share data (CSI 300 / CSI 500, configurable date range).

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

---

## 📖 What Is This

`skill-factor-loop-evolve` is an AI-agent skill for running a **local closed-loop
factor evolution pipeline**. In traditional factor research, the researcher
manually writes factors, backtests them one by one, analyzes results by hand,
and improves based on intuition. This skill automates the entire process:

1. **Validate** — checks syntax, allowed fields, look-ahead bias, and
   numerical stability. Bad candidates are rejected before any backtest.
2. **Fixed backtest** — uses PandaData API for real A-share data with a
   consistent cross-sectional long-short engine (configurable universe,
   frequency, label, cost). Results are comparable across iterations.
   Portfolio returns use the rebalance date with **no look-ahead bias**.
   Turnover is measured from actual position changes between rebalances.
3. **Diagnose & classify** — computes IC, ICIR, Sharpe, return, drawdown,
   turnover, coverage, stability, long/short behavior, and correlation.
   First-match classification: invalid → overfit → unstable → duplicate →
   weak → promising.
4. **Experience memory** — persists lessons from every run: which fields
   worked, which templates failed, which structures caused high turnover,
   which variants were too correlated, which refinements improved stability.
5. **Controlled variant generation** — selects strongest current factors as
   parents by **actual Sharpe** (highest first). **By default uses LLM-driven
   semantic transformations** (configurable in `config.json`; falls back to 12
   hard-coded transforms when disabled). The LLM proposes transforms based on
   full diagnostic profiles, experience memory, and the original user query.
6. **Iterate** — repeats steps 1–5 until N rounds complete, improvement
   stalls, or max iterations reached.

**Requires PandaData** — `pip install panda_data` and credentials in `.env`.

---

## 📥 Input Modes & Examples

The skill accepts factor expressions as input in four ways: **explicit expression**, **random generation**, **user instructions**, or **document extraction**.

### Input 1️⃣: Explicit Factor Expression (most direct)

Give one or more compliant factor expressions directly. The agent wraps them into factor objects and feeds them into the pipeline. Best when you already have a clear idea.

```text
User: Optimize this factor: rank(returns(close,20) / ts_std(returns(close,1),60))
```

The agent auto-fills metadata (`name`, `description`, `rationale`) and starts the optimization loop. Multiple expressions can be given at once:

```text
User: Optimize these three factors:
  - returns(close,20) - returns(close,5)
  - zscore(decay_linear(returns(close,1), 20) * volume)
  - (high - low) / ts_mean(close, 10)
```

### Input 2️⃣: Random Generation

The agent randomly combines allowed fields and functions to produce 5–15 candidates. Best for exploratory research — when you don't know what works, cast a wide net. For example, auto-generating combos like `returns(close,5) * rank(volume)`, `-ts_rank(returns(close,1),20)`, `ts_argmax(volume,60)`, etc.

```text
User: Randomly generate 10 factors and run 5 iterations
```

### Input 3️⃣: From User Instructions

Describe your research direction in natural language. The agent translates the intent into compliant factor expressions.

```text
User: Optimize a momentum factor with a 20-day window, risk adjustment, and
      outlier exclusion. Run 3 iterations.
```

The agent interprets this and generates related factor variants such as `returns(close,20)` (base), `returns(close,20)/ts_std(returns(close,1),60)` (risk-adjusted), `clip(returns(close,20), -0.15, 0.15)` (clipped), `rank(returns(close,20))` (ranked), `decay_linear(returns(close,1),20)` (decay-weighted), etc.

More user instruction examples:

| User Instruction | Agent Interpretation | Candidate Direction |
|------------------|---------------------|---------------------|
| "Optimize a low-turnover value factor" | Value + low turnover | `rank(1/close)`, `ts_mean(close,60)/close`, etc. |
| "Find a volume-price divergence signal" | Price vs volume trend divergence | `correlation(close,volume,20)`, `returns(close,10)-delta(volume,10)`, etc. |
| "Improve a quality factor to Sharpe > 0.8" | High quality + target Sharpe | ROE proxies, low volatility, stable growth factors |
| "Run 5 rounds of random exploration" | No specific direction, broad search | Random combos across fields and functions |
| "Optimize reversal factor from research paper" | Reversal + literature reference | Short-term reversal, overnight reversal, sector-adjusted reversal |

### Input 4️⃣: From Documents / Research Papers

Provide a research document (PDF, Markdown, paper abstract). The agent extracts factor descriptions and converts them to compliant expressions.

```text
User: This paper says "volume-weighted 20-day momentum outperforms traditional
      momentum — sum daily returns over 20 days weighted by daily volume,
      then cross-sectionally standardize." Extract and optimize this factor.
```

The agent extracts and generates compliant variants such as `zscore(decay_linear(returns(close,1)*volume,20))` (decay-weighted), `rank(decay_linear(returns(close,1)*volume,20))` (rank variant), `ts_sum(returns(close,1)*volume,20)/ts_sum(volume,20)` (simplified), etc.

### Input Format Reference

Regardless of input method, each factor is ultimately represented as a JSON object with these fields. The agent fills metadata automatically.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Unique ID, snake_case, e.g. `risk_adj_mom_20d` |
| `expression` | string | ✅ | Compliant formula using 6 fields + allowed functions only |
| `description` | string | ✅ | One-sentence description of what the factor does |
| `rationale` | string | ✅ | Economic or statistical justification |
| `generation` | string | ✅ | Source: `manual` / `random` / `document` / `variant-*` |
| `parent` | string | ❌ | Parent factor name (for variants only) |
| `transformation` | string | ❌ | Description of transformation applied (for variants only) |

> ⚠️ The validator will automatically reject expressions that violate the [factor contract](references/factor-contract.md).

---

## ⚙️ Hyperparameters

All hyperparameters live in `config.json` with `_help` documentation for
each field. Edit the file directly to tune behavior. `config.json` is
auto-copied to each run output for reproducibility.

> 💡 **User Query Overrides**: When the user explicitly specifies a hyperparameter in their query (e.g. "run 10 iterations", "5 parents per round", "at least 2 transformations"), the agent overrides the corresponding `config.json` default with the user-specified value, for that run only.

---

## 🔍 How to Interpret Results

After a run, `output/<run_id>/` contains:

### Core Output Files

| File | Content | How to Use |
|------|---------|------------|
| `final_summary.json` | **Summary**: optimization log, top 5 factors, Pareto frontier, worth_keeping, original query, active config, evolution diagram | Read first for high-level picture |
| `evolution_diagram.md` | **Evolution graph**: Mermaid flowchart + backtest config + top 10 factors table + transformation reference (only shows transforms actually used, with LLM rationales) | Preview with Cmd+Shift+V in VS Code |
| `diagnosis.json` | **Diagnosis**: per-factor class, Sharpe, IC, turnover, suggestions | Deep-dive into each factor |
| `backtest_results_all.json` | **All backtests**: accumulated results across all iterations | Compare metrics across iterations |
| `knowledge_base.json` | **Experience memory**: successful patterns, failed patterns, field effectiveness | Understand what consistently works |
| `transform_suggestions.json` | **LLM suggestions**: specific transforms proposed by LLM with detailed rationales (kept in LLM mode) | Understand LLM's transform reasoning |
| `candidate_evolution.json` | **Genealogy tree**: parent-child relationships with per-node metrics + original query | Trace factor evolution path |
| `config.json` | **Run config**: full config snapshot | Reproduce the run |

---

## 🧬 Evolution: How Transformations Work

### Transformation Mode

Controlled by `config.json` → `transformations.use_llm_transforms`:

- **`true` (default)** — LLM-driven semantic transformations. The LLM receives
  each parent factor's full diagnostic profile (Sharpe, IC, turnover, drawdown,
  long/short returns), experience memory (successful/failed patterns, field
  effectiveness), and the original user query. It proposes semantically
  meaningful changes
- **`false`** — original 12 hard-coded transformations.

Override with `--use-llm` (force LLM) or `--no-llm` (force static).

### Static Transformations (when LLM is disabled)

| Transformation | Rationale |
|---------------|-----------|
| `flip-sign` | Negative Sharpe — inverting recovers a positive Sharpe from a directionally-wrong factor |
| `reduce-turnover` | Turnover > 0.8 — smoothing reduces excessive trading and transaction costs |
| `adjust-lookback` | IC signal too noisy or too smooth — changing lookback window can improve stability |
| `adjust-smoothing` | Turnover extreme — adjusting smoothing balances signal decay vs. trading cost |
| `adjust-clipping` | Extreme outliers distort the signal — clipping caps their influence |
| `adjust-normalization` | Distribution skewed — switching normalization improves cross-sectional comparability |
| `combine-factors` | Both promising with low correlation — combining diversifies the alpha source |
| `simplify` | Expression over-complex — removing nesting reduces overfit risk |
| `remove-component` | Sub-component is weak — removing it purifies the remaining signal |
| `long-only` | Short leg underperforming — keeping only longs eliminates dead-weight shorts |
| `short-only` | Long leg underperforming — keeping only shorts eliminates dead-weight longs |
| `asymmetric` | Long/short returns asymmetric — weighting captures the stronger side more heavily |

---

## 🚀 Quick Start

### Prerequisites

Create `.env` at the skill root:

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

### Agent Workflow

```text
User: Optimize momentum factors for 3 iterations

Agent:
1. Setup: set FACTOR_OPTIMIZE_RUN_DIR, init knowledge base
2. Place initial candidates as candidates.json
3. For each iteration:
   - Validate: python scripts/validator.py --factors candidates.json
   - Backtest: python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json
   - Diagnose: python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json
   - Learn: python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json
   - LLM transforms (default):
     python scripts/llm_suggest.py --generate-prompt ... → feed to LLM → save response →
     python scripts/llm_suggest.py --apply-response ... → produces transform_suggestions.json
   - Generate: python scripts/generate_candidates.py ... --query "$USER_QUERY"
     (auto-detects and uses LLM suggestions by default; falls back to static if not found)
4. Summary: python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json
5. Report: optimization log, top 5 factors, Pareto frontier, worth keeping, key patterns
```

### Direct Tool Usage

```bash
# Set run directory (auto-timestamped)
export FACTOR_OPTIMIZE_RUN_DIR="output/run_$(date +%Y%m%d_%H%M%S)"

# Init knowledge base inside output
python scripts/knowledge_base.py --init --output "$FACTOR_OPTIMIZE_RUN_DIR/knowledge_base.json"

# Validate → backtest → diagnose → learn → generate (repeat per iteration)
python scripts/validator.py --factors candidates.json
python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json
python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json
python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json

# 🆕 LLM transforms by default (auto-detects transform_suggestions.json; falls back gracefully)
python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json --query "$USER_QUERY"
# Or force static transforms:
python scripts/generate_candidates.py ... --no-llm

# Final summary
python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json
```

All paths are relative to the output run directory. Set `FACTOR_OPTIMIZE_RUN_DIR`
for pipeline continuity across script calls.

---

## 📦 Directory Structure

```
skill-factor-loop-evolve/
├── SKILL.md                              # Entry point (YAML + agent instructions)
├── README.md / README.en.md              # Documentation
├── config.json                           # All hyperparameters + _help docs
├── LICENSE                               # GPL-3.0
├── requirements.txt                      # numpy, pandas, pyyaml, python-dotenv, panda_data
├── references/
│   ├── factor-contract.md                # 📚 Factor field/function contract
│   ├── optimization-protocol.md          # 🔄 Loop protocol, classification, stopping criteria
│   └── agent-integration.md              # 🔌 Multi-agent install & smoke test
├── scripts/
│   ├── contracts.py                      # Shared contracts + config loader (single source of truth)
│   ├── validator.py                      # 🧪 Factor validator (syntax, look-ahead, stability)
│   ├── backtest.py                       # 📊 Backtest engine (PandaData real A-share data)
│   ├── diagnose.py                       # 🔍 Factor diagnosis & classification
│   ├── knowledge_base.py                 # 🧠 Experience memory + active learning
│   ├── generate_candidates.py            # 🔀 Variant generation (LLM-first, static fallback)
│   ├── llm_suggest.py                    # 🤖 LLM transform suggestion engine
│   └── optimizer.py                      # 🔁 Loop coordinator + evolution diagram + Pareto frontier
├── agents/
│   ├── openai.yaml                       # OpenAI/Codex adapter
│   ├── cursor-rule.mdc                   # Cursor rule adapter
│   └── portable-loader.md                # Generic agent loader
└── output/
    └── <run-id>/                         # One subfolder per run
        ├── backtest_results_all.json     # All iterations accumulated
        ├── diagnosis.json                # Classification + metrics + suggestions
        ├── knowledge_base.json           # Experience memory
        ├── candidate_evolution.json      # Full genealogy tree + original query
        ├── transform_suggestions.json    # LLM transform suggestions (LLM mode)
        ├── final_summary.json            # Summary report + Pareto frontier
        ├── evolution_diagram.md          # Mermaid evolution graph + backtest config
        ├── config.json                   # Run config (reproducible)
        └── trading_data/                 # CSV: returns, IC, positions
```

---

## ⚠️ Disclaimer

This repository is for research methodology documentation only and does not constitute any investment advice.

## 👤 Maintainer

Created and maintained by `davideliu` (QuantSkills community).

## 📜 License

GPL-3.0. See [LICENSE](LICENSE).
