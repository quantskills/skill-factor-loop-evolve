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
