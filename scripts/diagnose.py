#!/usr/bin/env python3
"""Factor diagnosis and classification for skill-factor-loop-evolve.

Analyzes backtest results to compute IC, ICIR, Sharpe, return, drawdown,
turnover, coverage, stability, long/short behavior, and correlation.
Classifies each factor as promising, weak, duplicate, unstable, overfit,
or invalid.

Usage::

    python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import (  # noqa: E402
    VALID_CLASSIFICATIONS,
    CLASSIFICATION_CRITERIA,
    output_path as _resolve_output,
)


def compute_correlation_between_factors(
    results: list[dict],
) -> dict[str, float]:
    """Compute pairwise Spearman rank correlation between factor IC series.

    Uses actual IC time series when available; falls back to the structural
    similarity proxy only when IC series are missing.
    """
    cors = {}

    # Build a lookup of IC series by factor name
    ic_series_by_name: dict[str, list[float]] = {}
    for r in results:
        name = r.get("name", "")
        td = r.get("_trading_data", {})
        ic_list = td.get("ic_series", [])
        if ic_list and len(ic_list) >= 5:
            ic_series_by_name[name] = ic_list

    for i, r1 in enumerate(results):
        for j, r2 in enumerate(results):
            if i >= j:
                continue
            key = f"{r1['name']}__vs__{r2['name']}"
            n1 = r1.get("name", "")
            n2 = r2.get("name", "")

            if n1 in ic_series_by_name and n2 in ic_series_by_name:
                # Use actual IC series correlation (Spearman rank)
                ic1 = np.array(ic_series_by_name[n1])
                ic2 = np.array(ic_series_by_name[n2])
                # Align to minimum length
                min_len = min(len(ic1), len(ic2))
                if min_len >= 5:
                    from scipy.stats import spearmanr as _spearmanr
                    try:
                        corr_val, _ = _spearmanr(ic1[:min_len], ic2[:min_len])
                        cors[key] = round(float(corr_val), 4) if not np.isnan(corr_val) else 0.0
                    except Exception:
                        cors[key] = 0.0
                else:
                    cors[key] = 0.0
            else:
                # Fallback: structural similarity proxy
                e1 = r1.get("expression", "")
                e2 = r2.get("expression", "")
                shared_tokens = set(e1.split("(")) & set(e2.split("("))
                total_tokens = set(e1.split("(")) | set(e2.split("("))
                if total_tokens:
                    cors[key] = round(len(shared_tokens) / len(total_tokens), 4)
                else:
                    cors[key] = 0.0
    return cors


def classify_factor(
    factor_result: dict,
    correlations: dict[str, float],
) -> str:
    """Classify a single factor based on its backtest metrics.

    Order of checks (first match wins):
    1. invalid — failed backtest, NaN/inf, very low coverage
    2. overfit — extreme top-quantile concentration
    3. unstable — high IC volatility, sign flips
    4. duplicate — high correlation with another factor
    5. weak — low IC, ICIR, Sharpe
    6. promising — meets all thresholds
    """
    name = factor_result.get("name", "")

    # Invalid check
    if "error" in factor_result:
        return "invalid"

    coverage = factor_result.get("coverage", 0)
    if coverage < CLASSIFICATION_CRITERIA["invalid"]["coverage_min"]:
        return "invalid"

    # Check for NaN/Inf in key metrics
    for key in ["ic_mean", "icir", "sharpe"]:
        val = factor_result.get(key, 0)
        if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
            return "invalid"

    sharpe = factor_result.get("sharpe", 0)
    ic_mean = factor_result.get("ic_mean", 0)
    ic_std = factor_result.get("ic_std", 0)
    icir = factor_result.get("icir", 0)
    turnover = factor_result.get("turnover", 0)

    # Overfit check — extreme Sharpe with weak IC
    if (sharpe > CLASSIFICATION_CRITERIA["overfit"]["sharpe_extreme"] or sharpe < -CLASSIFICATION_CRITERIA["overfit"]["sharpe_extreme"]) and abs(ic_mean) < CLASSIFICATION_CRITERIA["overfit"]["ic_weak"]:
        return "overfit"

    # Unstable check
    if ic_std > 0 and abs(ic_mean) > 0:
        if ic_std / abs(ic_mean) > CLASSIFICATION_CRITERIA["unstable"]["ic_std_ratio"]:
            return "unstable"

    # Duplicate check
    for key, corr_val in correlations.items():
        if name in key and corr_val > CLASSIFICATION_CRITERIA["duplicate"]["correlation_threshold"]:
            return "duplicate"

    # Weak check — Sharpe near zero (weak in either direction)
    weak_lo = CLASSIFICATION_CRITERIA["weak"].get("sharpe_min", -0.3)
    weak_hi = CLASSIFICATION_CRITERIA["weak"].get("sharpe_max", 0.3)
    if (sharpe > weak_lo and sharpe < weak_hi and
            abs(ic_mean) < CLASSIFICATION_CRITERIA["weak"]["ic_max"] and
            abs(icir) < CLASSIFICATION_CRITERIA["weak"]["icir_max"]):
        return "weak"

    # Promising check — strong predictive power (positive Sharpe is good)
    # Turnover is NOT a gate for promising — it's a cost concern, not predictive.
    if (abs(ic_mean) >= CLASSIFICATION_CRITERIA["promising"]["ic_min"] and
            abs(icir) >= CLASSIFICATION_CRITERIA["promising"]["icir_min"] and
            sharpe >= CLASSIFICATION_CRITERIA["promising"]["sharpe_min"] and
            coverage >= CLASSIFICATION_CRITERIA["promising"]["coverage_min"]):
        return "promising"

    # Default: not enough signal to classify — mark as weak
    return "weak"


def diagnose(
    backtest_results: dict,
    factors: list[dict],
) -> dict:
    """Run full diagnosis on backtest results.

    Args:
        backtest_results: Output from backtest.py.
        factors: The validated factor definitions.

    Returns:
        Diagnosis dict with classifications, diagnostics, and recommendations.
    """
    factor_results = backtest_results.get("factor_results", [])
    correlations = compute_correlation_between_factors(factor_results)

    classifications = {}
    diagnostics = []

    for fr in factor_results:
        name = fr.get("name", "unnamed")
        classification = classify_factor(fr, correlations)

        # Build per-factor diagnostic
        factor_def = next((f for f in factors if f.get("name") == name), {})

        diag = {
            "name": name,
            "expression": fr.get("expression", ""),
            "_iteration": fr.get("_iteration", 1),
            "classification": classification,
            "sharpe": fr.get("sharpe"),
            "ic_mean": fr.get("ic_mean"),
            "turnover": fr.get("turnover"),
            "diagnosis_notes": [],
            "improvement_suggestions": [],
        }

        # Add specific diagnosis notes
        c = classification
        if c == "promising":
            diag["diagnosis_notes"].append(
                "Factor meets all performance thresholds — good candidate for parent."
            )
            turnover_val = fr.get("turnover", 0)
            if turnover_val > 0.6:
                diag["improvement_suggestions"].append(
                    "Consider reduce-turnover transformation to lower turnover."
                )
        elif c == "weak":
            diag["diagnosis_notes"].append(
                "Factor has low predictive power — consider as component in combination."
            )
            diag["improvement_suggestions"].append(
                "Try combine-factors with another promising factor."
            )
        elif c == "duplicate":
            diag["diagnosis_notes"].append(
                "Highly correlated with another factor — redundant."
            )
            diag["improvement_suggestions"].append(
                "Remove or merge with its duplicate."
            )
        elif c == "unstable":
            diag["diagnosis_notes"].append(
                "High IC volatility — try smoothing or longer lookback."
            )
            diag["improvement_suggestions"].append(
                "Try adjust-smoothing or adjust-lookback transformations."
            )
        elif c == "overfit":
            diag["diagnosis_notes"].append(
                "Suspiciously high returns with low IC — likely overfit."
            )
            diag["improvement_suggestions"].append(
                "Try simplify transformation to reduce complexity."
            )
        elif c == "invalid":
            diag["diagnosis_notes"].append(
                f"Factor failed backtest or has insufficient coverage."
            )

        classifications[name] = classification
        diagnostics.append(diag)

    # Summary stats
    n_total = len(factor_results)
    n_promising = sum(1 for v in classifications.values() if v == "promising")
    n_weak = sum(1 for v in classifications.values() if v == "weak")
    n_duplicate = sum(1 for v in classifications.values() if v == "duplicate")
    n_unstable = sum(1 for v in classifications.values() if v == "unstable")
    n_overfit = sum(1 for v in classifications.values() if v == "overfit")
    n_invalid = sum(1 for v in classifications.values() if v == "invalid")

    # Best factor — highest actual Sharpe
    best_factor = None
    best_sharpe = -999.0
    for fr in factor_results:
        if "error" not in fr:
            s = fr.get("sharpe", 0) or 0
            if s > best_sharpe:
                best_sharpe = s
                best_factor = fr.get("name")

    # Stagnation check
    promising_sharpes = [
        fr.get("sharpe", 0) for fr in factor_results
        if classifications.get(fr.get("name")) == "promising" and "error" not in fr
    ]
    avg_promising_sharpe = (
        round(float(np.mean(promising_sharpes)), 4) if promising_sharpes else 0.0
    )

    return {
        "n_total": n_total,
        "n_promising": n_promising,
        "n_weak": n_weak,
        "n_duplicate": n_duplicate,
        "n_unstable": n_unstable,
        "n_overfit": n_overfit,
        "n_invalid": n_invalid,
        "classifications": classifications,
        "diagnostics": diagnostics,
        "best_factor": best_factor,
        "best_sharpe": best_sharpe,
        "avg_promising_sharpe": avg_promising_sharpe,
        "correlations": correlations,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose backtest results and classify factors."
    )
    parser.add_argument("--results", type=str, required=True,
                        help="Path to backtest results JSON.")
    parser.add_argument("--factors", type=str, required=True,
                        help="Path to validated factors JSON.")
    parser.add_argument("--output", type=str, default="",
                        help="Output path for diagnosis (default: output/<run-id>/diagnosis.json).")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Run identifier. Auto-generated timestamp if not given.")
    args = parser.parse_args()

    results_path = Path(args.results)
    factors_path = Path(args.factors)

    if not results_path.is_file():
        print(json.dumps({"error": f"File not found: {args.results}"}, ensure_ascii=False))
        sys.exit(1)
    if not factors_path.is_file():
        print(json.dumps({"error": f"File not found: {args.factors}"}, ensure_ascii=False))
        sys.exit(1)

    backtest_results = json.loads(results_path.read_text(encoding="utf-8-sig"))
    factors = json.loads(factors_path.read_text(encoding="utf-8-sig"))

    # ── Handle backtest_results_all.json format (iterations array) ─────
    if "iterations" in backtest_results and "factor_results" not in backtest_results:
        iterations = backtest_results["iterations"]
        if iterations:
            latest = iterations[-1]
            # Flatten: add factor_results at top level for diagnose()
            backtest_results = {
                "factor_results": latest.get("factor_results", latest.get("results", [])),
                "total": latest.get("total", len(latest.get("factor_results", []))),
                "passed": latest.get("passed", 0),
                "failed": latest.get("failed", 0),
            }
        else:
            backtest_results = {"factor_results": [], "total": 0, "passed": 0, "failed": 0}

    diagnosis = diagnose(backtest_results, factors)

    out = args.output if args.output else str(_resolve_output("diagnosis.json"))
    Path(out).write_text(
        json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(diagnosis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
