#!/usr/bin/env python3
"""Experience memory (knowledge base) manager for skill-factor-optimize.

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
    output_path as _resolve_output,
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
