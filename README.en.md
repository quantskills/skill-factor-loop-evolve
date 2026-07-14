# Factor Loop Evolve

**English** | [简体中文](README.md)

Local closed-loop factor evolution for AI agents: generate candidate factors,
validate them, backtest on PandaData A-share data, diagnose performance, ask an
LLM for semantic improvements, and repeat.

This skill is for research workflows only. It is not investment advice.

## What It Does

- Validates factor expressions against the allowed field/function contract.
- Runs a consistent long-short backtest on real A-share OHLCV data.
- Diagnoses each factor with Sharpe, IC, turnover, drawdown, and classification.
- Keeps a run-local knowledge base of useful and failed patterns.
- Prioritizes LLM-generated factor improvements before static transforms.
- Produces a final summary and evolution diagram for review.

## Inputs

You can start from:

- One or more explicit factor expressions.
- A natural-language factor idea, such as momentum, reversal, or volume-price divergence.
- A random exploration request.
- A research note, report, or paper excerpt that describes factor logic.

If no explicit target/output is given, the default objective is to increase
Sharpe, starting from factors invented by the agent.

All generated expressions must follow [the factor contract](references/factor-contract.md).

Example requests:

```text
Optimize this factor for 3 iterations:
rank(returns(close,20) / ts_std(returns(close,1),60))
```

```text
Generate 10 momentum and reversal candidates, then run 5 evolution rounds.
```

## Setup

Create `.env` in the skill root:

```bash
PANDA_AI_USERNAME="your_username"
PANDA_AI_PASSWORD="your_password"
PANDA_AI_BASE_URL="http://pandadata.pandaaiquant.com"
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Results

Read `final_summary.json` first. It contains:

- Sharpe progression by iteration.
- Top factors.
- Pareto frontier.
- Worth-keeping decision.
- Original query.
- Active config.

Other useful outputs:

- `diagnosis.json`: per-factor metrics and classifications.
- `backtest_results_all.json`: all iteration backtest results.
- `knowledge_base.json`: learned patterns from the run.
- `candidate_evolution.json`: parent-child factor lineage.
- `evolution_diagram.md`: visual evolution summary.
- `trading_data/`: portfolio returns, IC series, and positions.

## Build Alpha Library

After running the evolution pipeline multiple times, the `output/` directory
will contain many `run_*` folders. Use `build_alpha_library.py` to merge all
`final_summary.json` files into a unified alpha library, deduplicating by
expression (keeping the best Sharpe for each).

### Usage

```bash
# Basic: scan all run_* under output/ and generate alpha_library.json
python scripts/build_alpha_library.py

# Custom output path
python scripts/build_alpha_library.py --output my_library.json

# Only include factors with Sharpe ≥ 0.3
python scripts/build_alpha_library.py --min-sharpe 0.3

# Custom output directory
python scripts/build_alpha_library.py --output-dir /path/to/output
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--output` | Output JSON file path | `alpha_library.json` (skill root) |
| `--min-sharpe` | Minimum Sharpe threshold; factors below are excluded | No limit |
| `--output-dir` | Directory containing `run_*` folders | `./output/` |

### Output Format

The generated `alpha_library.json` structure:

```json
{
  "meta": {
    "total_factors": 60,
    "total_runs_scanned": 12,
    "total_runs_contributing": 12,
    "positive_sharpe_count": 28,
    "best_sharpe": 0.8656,
    "worst_sharpe": -0.4289,
    "min_sharpe_filter": null
  },
  "entries": [
    {
      "expression": "-1 * rank(delta(returns(close, 10), 5) / ...)",
      "sharpe": 0.8656,
      "source_run": "run_20260713_194041_model_creativity",
      "source_query": "use your creativity to generate powerful alphas",
      "worth_keeping": true,
      "slug": "1_rank_delta_returns_close_10_5_max_..."
    }
  ]
}
```

Each factor entry contains:

- `expression` — the factor expression.
- `sharpe` — annualized Sharpe ratio.
- `source_run` — source run directory name.
- `source_query` — the original query that triggered the run.
- `worth_keeping` — whether the run was deemed worth keeping.
- `slug` — a short identifier derived from the expression.

Factors are sorted by Sharpe descending. The `meta` block provides aggregate
statistics for a quick quality assessment of the library.

## Configuration

Edit `config.json` to change backtest dates, universe, costs, stopping rules,
classification thresholds, and transform settings.

If a user explicitly requests a setting, such as "run 10 iterations" or "use
CSI 500", that request should override the config for the current run.

## References

- `SKILL.md`: primary agent instructions.
- `references/factor-contract.md`: allowed fields, functions, and expression rules.
- `references/optimization-protocol.md`: loop protocol and classification rules.
- `references/agent-integration.md`: install and smoke-test guidance.

## License

GPL-3.0. See [LICENSE](LICENSE).
