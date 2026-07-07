#!/usr/bin/env python3
"""Shared contract definitions for the Factor Optimize skill.

Defines allowed fields, functions, classification taxonomy, transformation
catalog, backtest configuration, and knowledge base schema. This module is
the single source of truth — imported by all other scripts.

Usage::

    from contracts import (
        ALLOWED_FIELDS, ALLOWED_FUNCTIONS, VALID_CLASSIFICATIONS,
        VALID_TRANSFORMATIONS, DEFAULT_BACKTEST_CONFIG, build_correction_prompt
    )
"""

from __future__ import annotations

import json
from pathlib import Path

# ─── Load config.json (fall back to embedded defaults if missing) ──────────
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

def _load_config():
    """Load config.json. Returns empty dict if file missing or invalid."""
    if _CONFIG_PATH.is_file():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    return {}

_config = _load_config()

# ═══════════════════════════════════════════════════════════════════════════════
# Field & Function Contract
# ═══════════════════════════════════════════════════════════════════════════════

ALLOWED_FIELDS: frozenset[str] = frozenset({
    "open", "high", "low", "close", "volume", "amount",
})
"""The 6 OHLCV field variables available in every factor expression."""

ALLOWED_FUNCTIONS: frozenset[str] = frozenset({
    # Cross-sectional
    "rank", "zscore", "scale",
    # Time-series rolling
    "ts_rank", "ts_zscore", "ts_mean", "ts_std",
    "ts_max", "ts_min", "ts_sum",
    "ts_argmax", "ts_argmin",
    "correlation", "covariance", "decay_linear",
    # Lag / difference / returns
    "delay", "delta", "returns", "adv",
    # Element-wise math
    "sign", "log", "abs", "power", "signed_power",
    "min", "max", "clip",
})
"""The 27 helper functions available in every factor expression."""

ALLOWED_IDENTIFIERS: frozenset[str] = ALLOWED_FIELDS | ALLOWED_FUNCTIONS | {"_ref"}
"""All valid identifiers in expressions."""


# ═══════════════════════════════════════════════════════════════════════════════
# Factor Classification Taxonomy
# ═══════════════════════════════════════════════════════════════════════════════

VALID_CLASSIFICATIONS: frozenset[str] = frozenset({
    "promising",
    "weak",
    "duplicate",
    "unstable",
    "overfit",
    "invalid",
})
"""The 6 factor classification categories."""

CLASSIFICATION_CRITERIA: dict[str, dict] = {
    "promising": {
        "ic_min": _config.get("classification", {}).get("promising", {}).get("ic_min", 0.01),
        "icir_min": _config.get("classification", {}).get("promising", {}).get("icir_min", 0.05),
        "sharpe_min": _config.get("classification", {}).get("promising", {}).get("sharpe_min", 0.3),
        "turnover_max": _config.get("classification", {}).get("promising", {}).get("turnover_max", 0.85),
        "coverage_min": _config.get("classification", {}).get("promising", {}).get("coverage_min", 0.25),
    },
    "weak": {
        "ic_max": _config.get("classification", {}).get("weak", {}).get("ic_max", 0.02),
        "icir_max": _config.get("classification", {}).get("weak", {}).get("icir_max", 0.3),
        "sharpe_max": _config.get("classification", {}).get("weak", {}).get("sharpe_range", [-0.3, 0.3])[1],
        "sharpe_min": _config.get("classification", {}).get("weak", {}).get("sharpe_range", [-0.3, 0.3])[0],
    },
    "duplicate": {
        "correlation_threshold": _config.get("classification", {}).get("duplicate", {}).get("correlation_threshold", 0.85),
    },
    "unstable": {
        "ic_std_ratio": _config.get("classification", {}).get("unstable", {}).get("ic_std_ratio", 20.0),
    },
    "overfit": {
        "sharpe_extreme": _config.get("classification", {}).get("overfit", {}).get("sharpe_extreme", 3.0),
        "ic_weak": _config.get("classification", {}).get("overfit", {}).get("ic_weak", 0.01),
    },
    "invalid": {
        "coverage_min": _config.get("classification", {}).get("invalid", {}).get("coverage_min", 0.10),
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# Controlled Transformation Catalog
# ═══════════════════════════════════════════════════════════════════════════════

VALID_TRANSFORMATIONS: frozenset[str] = frozenset({
    "adjust-lookback",
    "adjust-smoothing",
    "adjust-clipping",
    "adjust-normalization",
    "combine-factors",
    "simplify",
    "reduce-turnover",
    "remove-component",
    "long-only",
    "short-only",
    "asymmetric",
    "flip-sign",
})
"""The 12 controlled transformation types."""

TRANSFORMATION_RATIONALE_MAP: dict[str, str] = {
    "adjust-lookback": "IC signal is too noisy or too smooth — changing the lookback window can improve stability",
    "adjust-smoothing": "Turnover is too high or too low — adjusting smoothing helps balance signal decay vs. trading cost",
    "adjust-clipping": "Extreme outliers are distorting the signal — clipping caps their influence for more robust rankings",
    "adjust-normalization": "Factor distribution is skewed — switching normalization method improves cross-sectional comparability",
    "combine-factors": "Both factors are promising with low correlation — combining them diversifies the alpha source",
    "simplify": "Expression is over-complex with high turnover — removing nesting reduces overfit risk without losing signal",
    "reduce-turnover": "Turnover exceeds 0.8 — smoothing the signal reduces excessive trading and transaction costs",
    "remove-component": "A sub-component is weak or noisy — removing it purifies the remaining signal",
    "long-only": "The short leg is underperforming — keeping only long positions eliminates dead-weight shorts",
    "short-only": "The long leg is underperforming — keeping only short positions eliminates dead-weight longs",
    "asymmetric": "Long and short returns are asymmetric — weighting them differently captures the stronger side more heavily",
    "flip-sign": "Sharpe is negative — inverting the expression sign recovers a positive Sharpe from a directionally-wrong factor",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Backtest Engine Configuration
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_BACKTEST_CONFIG: dict = {
    "cost_bps": _config.get("backtest", {}).get("cost_bps", 5.0),
    "holding_days": _config.get("backtest", {}).get("holding_days", 5),
    "n_quantiles": _config.get("backtest", {}).get("n_quantiles", 5),
    "long_pct": _config.get("backtest", {}).get("long_pct", 0.2),
    "short_pct": _config.get("backtest", {}).get("short_pct", 0.2),
    "lookback_min_days": _config.get("backtest", {}).get("lookback_min_days", 252),
    "universe": _config.get("backtest", {}).get("universe", "000300"),
    "start_date": _config.get("backtest", {}).get("start_date", "20240101"),
    "end_date": _config.get("backtest", {}).get("end_date", "20251231"),
    "exclude_st": _config.get("backtest", {}).get("exclude_st", True),
}
"""Default backtest engine configuration from config.json."""


# ═══════════════════════════════════════════════════════════════════════════════
# Knowledge Base Schema
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_KNOWLEDGE_BASE: dict = {
    "version": 1,
    "iterations_completed": 0,
    "successful_patterns": [],
    "failed_patterns": [],
    "field_effectiveness": {
        "close": 0,
        "volume": 0,
        "high": 0,
        "low": 0,
        "open": 0,
        "amount": 0,
    },
    "error_log": [],
    "high_turnover_structures": [],
    "high_correlation_pairs": [],
    "stability_improvements": [],
    "best_factor_history": [],
}

DEFAULT_TEMPLATES: list[dict] = [
    {
        "name": "momentum",
        "template": "returns(close, {n})",
        "description": "Simple price momentum over n periods",
        "typical_n": [5, 10, 20, 60, 120],
    },
    {
        "name": "risk_adj_momentum",
        "template": "returns(close, {n}) / ts_std(returns(close, 1), {m})",
        "description": "Momentum divided by volatility",
        "typical_n": [5, 10, 20],
        "typical_m": [20, 60, 120],
    },
    {
        "name": "mean_reversion",
        "template": "-(close - ts_mean(close, {n})) / ts_std(close, {n})",
        "description": "Normalized distance from rolling mean (negated)",
        "typical_n": [5, 10, 20, 60],
    },
    {
        "name": "volume_breakout",
        "template": "volume / ts_mean(volume, {n})",
        "description": "Volume relative to its rolling average",
        "typical_n": [5, 20, 60],
    },
    {
        "name": "price_volume_corr",
        "template": "correlation(close, volume, {n})",
        "description": "Rolling correlation between price and volume",
        "typical_n": [20, 60, 120],
    },
    {
        "name": "turnover_signal",
        "template": "rank(volume / ts_mean(volume, {n}))",
        "description": "Cross-sectional rank of relative volume",
        "typical_n": [20, 60],
    },
    {
        "name": "range_signal",
        "template": "(high - low) / close",
        "description": "Daily range as fraction of close price",
    },
    {
        "name": "gap_signal",
        "template": "(open - delay(close, 1)) / delay(close, 1)",
        "description": "Overnight gap as percentage",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Rules
# ═══════════════════════════════════════════════════════════════════════════════

ANTI_BIAS_RULES: str = """
CRITICAL — LOOK-AHEAD BIAS PREVENTION:
- delay(x, n), delta(x, n), and returns(x, n) MUST use n >= 1.
  n <= 0 peeks into the future -> REJECTED.
- All rolling functions (ts_*, correlation, covariance, decay_linear)
  inherently use only past data — this is correct.
"""

STABILITY_RULES: str = """
NUMERICAL STABILITY:
- No division by zero: use max(denom, 1e-8) as guard.
- No log of non-positive: use log(max(x, 1e-8)).
- Prefer rank() and zscore() based expressions — naturally stable.
- Avoid extreme power values — |n| > 5 in power(x, n) is warned.
"""

MAX_EXPRESSION_LENGTH: int = _config.get("validation", {}).get("max_expression_length", 500)
MAX_NESTING_DEPTH: int = _config.get("validation", {}).get("max_nesting_depth", 5)
MAX_FUNCTION_CALLS: int = _config.get("validation", {}).get("max_function_calls", 15)
MIN_ROLLING_N: int = _config.get("validation", {}).get("min_rolling_n", 2)
MAX_ROLLING_N: int = _config.get("validation", {}).get("max_rolling_n", 252)


# ═══════════════════════════════════════════════════════════════════════════════
# Stopping Criteria
# ═══════════════════════════════════════════════════════════════════════════════

STALL_ITERATIONS: int = _config.get("stopping", {}).get("stall_iterations", 2)
"""Consecutive iterations without Sharpe improvement to trigger stall."""
DIMINISHING_RETURN_THRESHOLD: float = _config.get("stopping", {}).get("diminishing_return_threshold", 0.02)
"""Minimum Sharpe improvement to avoid diminishing returns."""
MIN_ITERATIONS: int = _config.get("stopping", {}).get("min_iterations", 1)
"""Minimum iterations before early stopping is allowed."""
MAX_ITERATIONS: int = _config.get("stopping", {}).get("max_iterations", 5)
"""Maximum iterations (hard stop)."""
WORTH_KEEPING_SHARPE_THRESHOLD: float = _config.get("stopping", {}).get("worth_keeping_sharpe_threshold", 0.3)
"""Final report marks worth_keeping=true if best Sharpe >= this."""

# Parent selection
MIN_PARENTS: int = _config.get("parent_selection", {}).get("min_parents", 1)
MAX_PARENTS: int = _config.get("parent_selection", {}).get("max_parents", 3)
DUPLICATE_CORRELATION_THRESHOLD: float = _config.get("parent_selection", {}).get("duplicate_correlation_threshold", 0.7)

# Evolution diagram tags
TAG_HIGH_SHARPE: float = _config.get("evolution_tags", {}).get("high_sharpe", 0.5)
TAG_LOW_SHARPE_ABS: float = _config.get("evolution_tags", {}).get("low_sharpe_abs", 0.2)
TAG_HIGH_IC_ABS: float = _config.get("evolution_tags", {}).get("high_ic_abs", 0.02)
TAG_LOW_IC_ABS: float = _config.get("evolution_tags", {}).get("low_ic_abs", 0.01)
TAG_HIGH_TURNOVER: float = _config.get("evolution_tags", {}).get("high_turnover", 0.85)
TAG_LOW_TURNOVER: float = _config.get("evolution_tags", {}).get("low_turnover", 0.5)
TAG_HIGH_DRAWDOWN: float = _config.get("evolution_tags", {}).get("high_drawdown", -0.5)

# Transformations
MIN_TRANSFORMS: int = _config.get("transformations", {}).get("min_transforms_per_parent", 1)
MAX_TRANSFORMS: int = _config.get("transformations", {}).get("max_transforms_per_parent", 5)
REDUCE_TURNOVER_THRESHOLD: float = _config.get("transformations", {}).get("reduce_turnover_threshold", 0.8)
LOW_TURNOVER_THRESHOLD: float = _config.get("transformations", {}).get("low_turnover_threshold", 0.3)
FLIP_SIGN_SHARPE_THRESHOLD: float = _config.get("transformations", {}).get("flip_sign_sharpe_threshold", -0.3)
USE_LLM_TRANSFORMS: bool = _config.get("transformations", {}).get("use_llm_transforms", True)
"""If True (default), use LLM-driven semantic transform suggestions. If False, use original hard-coded transforms."""


# ═══════════════════════════════════════════════════════════════════════════════
# Correction Prompt Builder
# ═══════════════════════════════════════════════════════════════════════════════

def build_correction_prompt(failed_factors: list[dict]) -> str:
    """Build a correction prompt for the LLM to fix failed factors.

    Args:
        failed_factors: List of dicts with name, expression, error fields.

    Returns:
        A prompt string the agent can feed to its LLM.
    """
    lines = [
        "The following factor expressions failed validation. Please fix them.",
        "",
        "CONTRACT RULES:",
        "- Only these 6 fields: open, high, low, close, volume, amount",
        "- Only the 27 allowed functions (see factor-contract.md)",
        "- delay(x, n), delta(x, n), returns(x, n) MUST use n >= 1",
        "- No division by zero, no log of negative",
        f"- Max expression length: {MAX_EXPRESSION_LENGTH} chars",
        f"- Max nesting depth: {MAX_NESTING_DEPTH}",
        "",
        "FAILED FACTORS:",
    ]

    for f in failed_factors:
        name = f.get("name", "unknown")
        expr = f.get("expression", "")
        error = f.get("error", "unknown error")
        lines.append(f"\n### {name}")
        lines.append(f"Expression: `{expr}`")
        lines.append(f"Error: {error}")

    lines.extend([
        "",
        "Please provide corrected factor expressions with the SAME names.",
        "Output as a JSON array with: name, expression, description, rationale, generation.",
        "Return ONLY the JSON array, no other text.",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Output Directory Helper
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_output_dir(run_id: str | None = None) -> Path:
    """Resolve the output directory for a run.

    **Always** creates ``output/run_YYYYMMDD_HHMMSS/`` using the current
    timestamp. If the environment variable ``FACTOR_OPTIMIZE_RUN_DIR`` is set,
    that directory is used instead (enables multi-script pipelines to share
    the same output directory).

    Args:
        run_id: Ignored — run ID is always auto-generated from timestamp.

    Returns:
        Absolute Path to the output directory (created if needed).
    """
    import os
    from datetime import datetime

    skill_root = Path(__file__).resolve().parent.parent

    # Check for pipeline-continuity env var first
    env_dir = os.environ.get("FACTOR_OPTIMIZE_RUN_DIR", "")
    if env_dir:
        out_dir = Path(env_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir = skill_root / "output" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def output_path(
    filename: str,
    run_id: str | None = None,
    output_dir: str | None = None,
) -> Path:
    """Resolve a full output path for a file within a run directory.

    Args:
        filename: The base filename (e.g. ``results.json``).
        run_id: Optional run ID for auto-generated output dir.
        output_dir: Explicit output directory (overrides run_id).

    Returns:
        Absolute Path.
    """
    if output_dir:
        out = Path(output_dir)
    else:
        out = resolve_output_dir(run_id)
    out.mkdir(parents=True, exist_ok=True)
    return out / filename
