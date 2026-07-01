#!/usr/bin/env python3
"""Experience memory (knowledge base) manager for skill-factor-loop-evolve.

Manages the local knowledge base that persists lessons across iterations:
which fields worked, which templates failed, which errors recurred, which
structures caused high turnover, which variants were too correlated, and
which refinements improved stability.

Usage::

    python scripts/knowledge_base.py --init
    python scripts/knowledge_base.py --init --output my_kb.json
    python scripts/knowledge_base.py --learn diagnosis.json
    python scripts/knowledge_base.py --learn diagnosis.json --knowledge my_kb.json
    python scripts/knowledge_base.py --ingest existing_factors.json
    python scripts/knowledge_base.py --summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import (  # noqa: E402
    DEFAULT_KNOWLEDGE_BASE,
    DEFAULT_TEMPLATES,
    ALLOWED_FIELDS,
)


DEFAULT_KB_PATH = "knowledge_base.json"


def init_knowledge_base(output_path: str = DEFAULT_KB_PATH) -> dict:
    """Initialize a fresh knowledge base with default patterns."""
    kb = json.loads(json.dumps(DEFAULT_KNOWLEDGE_BASE))  # deep copy
    kb["templates"] = DEFAULT_TEMPLATES
    Path(output_path).write_text(
        json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return kb


def load_knowledge_base(path: str = DEFAULT_KB_PATH) -> dict:
    """Load existing knowledge base or create default."""
    p = Path(path)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8-sig"))
    return init_knowledge_base(path)


def save_knowledge_base(kb: dict, path: str = DEFAULT_KB_PATH) -> None:
    """Save knowledge base to disk."""
    Path(path).write_text(
        json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def learn_from_diagnosis(
    kb: dict,
    diagnosis: dict,
) -> dict:
    """Update knowledge base with lessons from a diagnosis.

    Args:
        kb: Current knowledge base.
        diagnosis: Diagnosis output from diagnose.py.

    Returns:
        Updated knowledge base.
    """
    kb["iterations_completed"] = kb.get("iterations_completed", 0) + 1

    diagnostics = diagnosis.get("diagnostics", [])
    classifications = diagnosis.get("classifications", {})

    for diag in diagnostics:
        name = diag.get("name", "")
        expr = diag.get("expression", "")
        classification = diag.get("classification", "unknown")
        suggestions = diag.get("improvement_suggestions", [])
        sharpe_val = diag.get("sharpe") or 0
        for field in ALLOWED_FIELDS:
            if field in expr:
                kb["field_effectiveness"][field] = kb.get("field_effectiveness", {}).get(field, 0) + 1

        # ── Successful patterns ──────────────────────────────────────────
        # Track ANY factor with meaningful predictive power (Sharpe < -0.2 or > +0.2)
        sharpe_val = diag.get("sharpe") or 0
        if sharpe_val < -0.2 or sharpe_val > 0.2:
            found = False
            for sp in kb.get("successful_patterns", []):
                if sp["pattern"] == expr:
                    sp["times_seen"] += 1
                    sp["avg_sharpe"] = round(
                        (sp["avg_sharpe"] * (sp["times_seen"] - 1) + sharpe_val)
                        / sp["times_seen"], 4
                    )
                    found = True
                    break
            if not found:
                kb.setdefault("successful_patterns", []).append({
                    "pattern": expr,
                    "context": f"Discovered in iteration {kb['iterations_completed']}",
                    "avg_sharpe": sharpe_val,
                    "times_seen": 1,
                })

        # ── Failed patterns ──────────────────────────────────────────────
        if classification in ("weak", "invalid"):
            for fp in kb.get("failed_patterns", []):
                if fp["pattern"] == expr:
                    fp["times_failed"] += 1
                    break

        # ── High turnover structures ─────────────────────────────────────
        turnover_val = diag.get("turnover")
        if turnover_val is not None and turnover_val > 0.8:
            kb.setdefault("high_turnover_structures", []).append({
                "name": name,
                "expression": expr,
                "turnover": turnover_val,
                "iteration": kb["iterations_completed"],
            })

        # ── Stability improvements ───────────────────────────────────────
        if any("reduce-turnover" in s or "adjust-smoothing" in s for s in suggestions):
            kb.setdefault("stability_improvements", []).append({
                "name": name,
                "suggestion": suggestions,
                "iteration": kb["iterations_completed"],
            })

        # ── Error log ────────────────────────────────────────────────────
        if classification == "invalid":
            kb.setdefault("error_log", []).append({
                "name": name,
                "expression": expr,
                "iteration": kb["iterations_completed"],
                "notes": diag.get("diagnosis_notes", []),
            })

    # ── High correlation pairs ──────────────────────────────────────────
    for key, corr_val in diagnosis.get("correlations", {}).items():
        if corr_val > 0.8:
            kb.setdefault("high_correlation_pairs", []).append({
                "pair": key,
                "correlation": corr_val,
                "iteration": kb["iterations_completed"],
            })

    # ── Best factor history ──────────────────────────────────────────────
    best_factor = diagnosis.get("best_factor")
    best_sharpe = diagnosis.get("best_sharpe", 0)
    if best_factor:
        kb.setdefault("best_factor_history", []).append({
            "iteration": kb["iterations_completed"],
            "factor": best_factor,
            "sharpe": best_sharpe,
        })

    return kb


def ingest_factors(kb: dict, factors: list[dict]) -> dict:
    """Ingest an existing factor library into the knowledge base.

    Args:
        kb: Current knowledge base.
        factors: List of factor definitions.

    Returns:
        Updated knowledge base with ingested patterns.
    """
    for factor in factors:
        name = factor.get("name", "")
        expr = factor.get("expression", "")
        rationale = factor.get("rationale", "")

        # Add as a successful pattern if it has a rationale
        if rationale:
            kb.setdefault("successful_patterns", []).append({
                "pattern": expr,
                "context": f"Ingested: {rationale[:100]}",
                "avg_sharpe": 0.0,
                "times_seen": 1,
            })

        # Track field usage
        for field in ALLOWED_FIELDS:
            if field in expr:
                kb["field_effectiveness"][field] = kb.get("field_effectiveness", {}).get(field, 0) + 1

    return kb


def summarize_knowledge(kb: dict) -> dict:
    """Generate a summary of the knowledge base."""
    return {
        "version": kb.get("version"),
        "iterations_completed": kb.get("iterations_completed", 0),
        "n_successful_patterns": len(kb.get("successful_patterns", [])),
        "n_failed_patterns": len(kb.get("failed_patterns", [])),
        "n_errors_logged": len(kb.get("error_log", [])),
        "n_high_turnover_structures": len(kb.get("high_turnover_structures", [])),
        "n_high_correlation_pairs": len(kb.get("high_correlation_pairs", [])),
        "n_stability_improvements": len(kb.get("stability_improvements", [])),
        "field_effectiveness": kb.get("field_effectiveness", {}),
        "best_factor_history": kb.get("best_factor_history", []),
        "top_successful_patterns": sorted(
            kb.get("successful_patterns", []),
            key=lambda x: x.get("avg_sharpe", 0), reverse=True
        )[:5],
        "top_failed_patterns": sorted(
            kb.get("failed_patterns", []),
            key=lambda x: x.get("times_failed", 0), reverse=True
        )[:5],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Active Knowledge Base — Insights for Parent Selection & Transform Guidance
# ═══════════════════════════════════════════════════════════════════════════════

def get_field_diversity(kb: dict) -> dict:
    """Compute field usage diversity metrics.

    Returns dict with:
    - pct: per-field usage percentage
    - overused: fields above 25% usage
    - underused: fields below 8% usage
    - gini: approximate concentration (0=uniform, 1=one field dominates)
    """
    field_eff = kb.get("field_effectiveness", {})
    total = sum(field_eff.values()) or 1
    pcts = {k: v / total for k, v in field_eff.items()}

    overused = [k for k, v in pcts.items() if v > 0.25]
    underused = [k for k, v in pcts.items() if v < 0.08 and total > 3]

    # Simple Gini-like concentration: max_pct - uniform_pct
    uniform = 1.0 / max(len(pcts), 1)
    max_pct = max(pcts.values()) if pcts else 0
    concentration = max(0.0, min(1.0, (max_pct - uniform) / (1.0 - uniform))) if uniform < 1.0 else 0.0

    return {
        "pct": {k: round(v, 3) for k, v in pcts.items()},
        "overused": overused,
        "underused": underused,
        "concentration": round(concentration, 3),
        "total_observations": total,
    }


def get_transform_effectiveness(kb: dict) -> dict:
    """Analyze which transformation types have been effective historically.

    Scans successful_patterns for pattern names that indicate specific
    transform types (rule-based transforms use ``_vN_transformname`` suffix;
    LLM transforms include the transform name in their name field).
    Returns per-transform success count and average Sharpe.
    """
    from contracts import VALID_TRANSFORMATIONS

    effectiveness = {t: {"success": 0, "avg_sharpe": 0.0} for t in VALID_TRANSFORMATIONS}

    for sp in kb.get("successful_patterns", []):
        pattern = sp.get("pattern", "")
        sharpe = sp.get("avg_sharpe", 0)
        # Rule-based transforms use suffix: name_vN_transformname
        # LLM transforms use: name_llm_transform-name
        for trans in VALID_TRANSFORMATIONS:
            if trans in pattern:
                prev = effectiveness[trans]
                prev["success"] += 1
                prev["avg_sharpe"] = round(
                    (prev["avg_sharpe"] * (prev["success"] - 1) + sharpe) / prev["success"], 4
                )

    result = {}
    for trans, counts in effectiveness.items():
        if counts["success"] > 0:
            result[trans] = {
                "success_count": counts["success"],
                "avg_sharpe": counts["avg_sharpe"],
            }

    return result


def get_convergence_warning(kb: dict) -> dict:
    """Detect if the system is converging to a local optimum.

    Checks:
    - Sharpe plateau (unchanged for ≥2 iterations)
    - Single-parent dominance (best factor unchanged for ≥2 iterations)
    - Field concentration (one field >50% usage)
    """
    best_hist = kb.get("best_factor_history", [])
    field_div = get_field_diversity(kb)

    warning = False
    reasons = []

    # Sharpe plateau check
    if len(best_hist) >= 3:
        recent = [h.get("sharpe", 0) for h in best_hist[-3:]]
        if max(recent) - min(recent) < 0.005:
            warning = True
            reasons.append("Sharpe plateau: no improvement for ≥3 iterations")

    # Single-parent dominance — check both rule-based (_v) and LLM (_llm_) prefixes
    if len(best_hist) >= 2:
        recent_factors = [h.get("factor", "") for h in best_hist[-2:]]
        if len(recent_factors) >= 2:
            base_names = []
            for f in recent_factors:
                if "_v" in f:
                    base_names.append(f.split("_v")[0])
                elif "_llm_" in f:
                    base_names.append(f.split("_llm_")[0])
                else:
                    base_names.append(f)
            if len(set(base_names)) == 1 and len(base_names) >= 2:
                warning = True
                reasons.append(f"Single-parent dominance: all best factors derive from '{base_names[0]}'")

    # Field concentration
    if field_div["concentration"] > 0.6:
        warning = True
        reasons.append(f"Field concentration {field_div['concentration']:.2f}: {field_div['overused']} dominate")

    return {
        "warning": warning,
        "reasons": reasons,
        "recommendation": "Generate fresh seed factors from underexplored families" if warning else "Continue current trajectory",
    }


def get_parent_diversity_boost(
    parents: list[dict],
    kb: dict,
    diversity_weight: float = 0.05,
) -> list[dict]:
    """Boost parent scores using active knowledge base insights.

    Rewards factors that:
    - Use underexplored fields (+diversity bonus)
    - Have successful pattern ancestry (+success bonus)
    - Are NOT similar to repeatedly failed patterns (-penalty)

    Returns parents with ``_effective_sharpe`` and ``_boost_reasons`` fields.
    """
    from contracts import ALLOWED_FIELDS

    field_eff = kb.get("field_effectiveness", {})
    total_field_uses = sum(field_eff.values()) or 1

    failed_patterns = {
        fp.get("pattern", ""): fp.get("times_failed", 0)
        for fp in kb.get("failed_patterns", [])
        if fp.get("times_failed", 0) >= 2
    }
    successful_patterns = {
        sp.get("pattern", ""): sp.get("avg_sharpe", 0)
        for sp in kb.get("successful_patterns", [])
    }

    for parent in parents:
        expr = parent.get("expression", "")
        base_sharpe = parent.get("sharpe") or 0
        boost = 0.0
        reasons = []

        # 1. Field diversity bonus
        for field in ALLOWED_FIELDS:
            if field in expr:
                field_usage_ratio = field_eff.get(field, 0) / max(total_field_uses, 1)
                if field_usage_ratio < 0.08 and total_field_uses > 3:
                    boost += diversity_weight
                    reasons.append(f"+diversity:{field}")

        # 2. Success pattern ancestry bonus
        for pat_expr in successful_patterns:
            if _token_overlap(expr, pat_expr) > 0.6:
                boost += diversity_weight * 0.6
                reasons.append("+ancestry")
                break

        # 3. Failed pattern similarity penalty
        for fp_expr, fail_count in failed_patterns.items():
            if _token_overlap(expr, fp_expr) > 0.7:
                boost -= diversity_weight * 1.5 * fail_count
                reasons.append(f"-failed_similar({fail_count}x)")
                break

        parent["_effective_sharpe"] = round(base_sharpe + boost, 4)
        parent["_boost"] = round(boost, 4)
        parent["_boost_reasons"] = reasons

    return parents


def _token_overlap(expr1: str, expr2: str) -> float:
    """Compute token-level Jaccard overlap between two expressions."""
    def _tokens(e: str) -> set[str]:
        return set(e.replace("(", " ").replace(")", " ").replace(",", " ").replace("/", " ").replace("*", " ").replace("+", " ").replace("-", " ").split())
    t1 = _tokens(expr1)
    t2 = _tokens(expr2)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage experience memory (knowledge base) for factor optimization."
    )
    parser.add_argument("--init", action="store_true",
                        help="Initialize a new knowledge base.")
    parser.add_argument("--learn", type=str, default="",
                        help="Learn from a diagnosis JSON file.")
    parser.add_argument("--ingest", type=str, default="",
                        help="Ingest an existing factor library JSON.")
    parser.add_argument("--summary", action="store_true",
                        help="Print knowledge base summary.")
    parser.add_argument("--knowledge", type=str, default=DEFAULT_KB_PATH,
                        help="Path to knowledge base file.")
    parser.add_argument("--output", type=str, default="",
                        help="Output path (defaults to --knowledge path).")
    args = parser.parse_args()

    output_path = args.output or args.knowledge

    if args.init:
        kb = init_knowledge_base(output_path)
        print(json.dumps({"status": "initialized", "path": output_path}, ensure_ascii=False))

    elif args.learn:
        kb = load_knowledge_base(args.knowledge)
        diag_path = Path(args.learn)
        if not diag_path.is_file():
            print(json.dumps({"error": f"File not found: {args.learn}"}, ensure_ascii=False))
            sys.exit(1)
        diagnosis = json.loads(diag_path.read_text(encoding="utf-8-sig"))
        kb = learn_from_diagnosis(kb, diagnosis)
        save_knowledge_base(kb, output_path)
        print(json.dumps({
            "status": "learned",
            "iterations_completed": kb["iterations_completed"],
            "path": output_path,
        }, ensure_ascii=False))

    elif args.ingest:
        kb = load_knowledge_base(args.knowledge)
        ingest_path = Path(args.ingest)
        if not ingest_path.is_file():
            print(json.dumps({"error": f"File not found: {args.ingest}"}, ensure_ascii=False))
            sys.exit(1)
        factors = json.loads(ingest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(factors, list):
            print(json.dumps({"error": "Ingest file must contain a JSON array."}, ensure_ascii=False))
            sys.exit(1)
        kb = ingest_factors(kb, factors)
        save_knowledge_base(kb, output_path)
        print(json.dumps({
            "status": "ingested",
            "n_factors": len(factors),
            "path": output_path,
        }, ensure_ascii=False))

    elif args.summary:
        kb = load_knowledge_base(args.knowledge)
        summary = summarize_knowledge(kb)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
