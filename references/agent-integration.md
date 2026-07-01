# Agent Integration — factor-loop-evolve

Install, load, and smoke-test `factor-loop-evolve` across agent runtimes.
**Keep the whole skill folder** — it depends on `references/` and `scripts/`.

**Prerequisites**: PandaData credentials in `.env` and the `panda_data` wheel
installed. The backtest engine uses real A-share data from PandaData.
PandaData is the default live-data source. For offline smoke tests or
reproducible fixtures, `scripts/backtest.py --data <ohlcv.csv>` accepts a local
CSV with `date,symbol,open,high,low,close,volume,amount` columns.

---

## Setup

```bash
# 1. Install the panda_data wheel (from the skill root or parent project)
pip install panda_data/panda_data-0.1.0-py3-none-any.whl

# 2. Create .env with PandaData credentials
cat > .env << 'EOF'
PANDA_AI_USERNAME="your_username"
PANDA_AI_PASSWORD="your_password"
PANDA_AI_BASE_URL="http://pandadata.pandaaiquant.com"
EOF

# 3. Install remaining dependencies
pip install -r requirements.txt
```

---

## Universal Smoke Test

From the skill root directory:

```bash
# 1. Verify contracts module
python -c "
import sys; sys.path.insert(0, 'scripts')
from contracts import (
    ALLOWED_FIELDS, ALLOWED_FUNCTIONS, VALID_CLASSIFICATIONS,
    VALID_TRANSFORMATIONS, DEFAULT_BACKTEST_CONFIG
)
assert len(ALLOWED_FIELDS) == 6, f'Expected 6 fields, got {len(ALLOWED_FIELDS)}'
assert len(ALLOWED_FUNCTIONS) == 27, f'Expected 27 functions, got {len(ALLOWED_FUNCTIONS)}'
assert len(VALID_CLASSIFICATIONS) == 6, f'Expected 6 classifications'
assert len(VALID_TRANSFORMATIONS) >= 10, f'Expected >=10 transformations'
print('Contracts OK')
"

# 2. Verify validator with test factors
echo '[{"name":"test_mom","expression":"returns(close,5)","description":"Momentum","rationale":"Test","generation":"initial"}]' > /tmp/smoke_factors.json
python scripts/validator.py --factors /tmp/smoke_factors.json

# 3. Verify backtest with a local fixture CSV
python -c "import sys; sys.path.insert(0, 'scripts'); from backtest import make_synthetic_market_data; make_synthetic_market_data(num_dates=300, num_symbols=30).to_csv('/tmp/smoke_ohlcv.csv', index=False)"
python scripts/backtest.py --factors /tmp/smoke_factors.json --data /tmp/smoke_ohlcv.csv --output /tmp/smoke_bt.json

# 4. Verify knowledge base init
python scripts/knowledge_base.py --init --output /tmp/smoke_kb.json
python -c "import json; kb=json.load(open('/tmp/smoke_kb.json')); assert kb['version']==1; print('KB OK')"

# 5. Verify full pipeline (diagnose → generate → learn → summary)
python scripts/diagnose.py --results /tmp/smoke_bt.json --factors /tmp/smoke_factors.json --output /tmp/smoke_diag.json
python scripts/knowledge_base.py --learn /tmp/smoke_diag.json --knowledge /tmp/smoke_kb.json --output /tmp/smoke_kb2.json
python scripts/generate_candidates.py --diagnosis /tmp/smoke_diag.json --knowledge /tmp/smoke_kb2.json --output /tmp/smoke_next.json --no-llm
python scripts/optimizer.py --summary --knowledge /tmp/smoke_kb2.json --output /tmp/smoke_summary.json
python -c "import json; s=json.load(open('/tmp/smoke_summary.json')); print(f'Summary: {s[\"iterations\"]} iterations')"
```

**Expected**: All checks pass with "OK" messages.

---

## How This Skill Works (Agent-Native)

1. **You** (the agent) read `SKILL.md`, `references/factor-contract.md`,
   and `references/optimization-protocol.md`.
2. **You** set `FACTOR_OPTIMIZE_RUN_DIR` and initialize the knowledge base
   inside the output directory.
3. **You** place initial candidates as `candidates.json` in the output directory.
4. **You** run `scripts/validator.py` to catch errors before backtesting.
5. **You** run `scripts/backtest.py` which fetches real A-share data from
   **PandaData API** (CSI 300, 2024-2025 by default, configurable via `config.json`).
6. **You** run `scripts/diagnose.py` to classify and analyze results.
7. **You** run `scripts/knowledge_base.py --learn` to persist lessons.
8. **You** run `scripts/generate_candidates.py` to create the next batch.
9. **You** repeat steps 4–8 for N iterations, then run `scripts/optimizer.py --summary`.

Key commands per iteration:

```bash
python scripts/validator.py --factors <candidates.json>
python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json
python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json
python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json
python scripts/llm_suggest.py --generate-prompt --diagnosis diagnosis.json --knowledge knowledge_base.json --query "$USER_QUERY" --output transform_prompt.md
# Feed transform_prompt.md to an LLM, save JSON as llm_response.json, then:
python scripts/llm_suggest.py --apply-response --response llm_response.json --diagnosis diagnosis.json --output transform_suggestions.json
python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json
```

**Dependencies**: `numpy`, `pandas`, `pyyaml`, `python-dotenv`, and the
`panda_data` wheel. PandaData credentials must be set in `.env`.

---

## Claude Code

```bash
mkdir -p ~/.claude/skills
rsync -a --exclude '__pycache__' ./ ~/.claude/skills/factor-loop-evolve/
```

Use: `Optimize momentum factors for 3 iterations using $factor-loop-evolve.`

---

## Codex

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
rsync -a --exclude '__pycache__' ./ "${CODEX_HOME:-$HOME/.codex}/skills/factor-loop-evolve/"
```

Use: `Use $factor-loop-evolve to run 3 iterations of factor evolution on momentum factors.`

---

## OpenClaw

```bash
mkdir -p ~/.openclaw/skills
rsync -a --exclude '__pycache__' ./ ~/.openclaw/skills/factor-loop-evolve/
```

---

## Cursor

```bash
mkdir -p .cursor/skills .cursor/rules
rsync -a --exclude '__pycache__' ./ .cursor/skills/factor-loop-evolve/
```
Create `.cursor/rules/factor-loop-evolve.mdc` from `agents/cursor-rule.mdc`.
