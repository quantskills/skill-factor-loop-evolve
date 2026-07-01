#!/usr/bin/env python3
"""LLM-driven transformation suggestion engine for skill-factor-loop-evolve.

Generates structured prompts for an LLM to rank transformations based on
backtest diagnostics, knowledge base insights, and the original user query.
Also applies LLM-suggested expression modifications.

Usage::

    # Generate a prompt for the LLM
    python scripts/llm_suggest.py --generate-prompt \
        --diagnosis diagnosis.json --knowledge kb.json \
        --query "Find momentum factors" \
        --output transform_prompt.md

    # Apply LLM response to generate transform suggestions
    python scripts/llm_suggest.py --apply-response \
        --response llm_response.json \
        --output transform_suggestions.json

    # Generate KB context summary for LLM consumption
    python scripts/llm_suggest.py --kb-context --knowledge kb.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import (  # noqa: E402
    ALLOWED_FIELDS,
    ALLOWED_FUNCTIONS,
    output_path as _resolve_output,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Prompt Generation
# ═══════════════════════════════════════════════════════════════════════════════

def _format_parent_profile(parent: dict, rank: int) -> str:
    """Format a single parent factor's diagnostic profile for the LLM prompt."""
    expr = parent.get("expression", "")
    name = parent.get("name", "")
    sharpe = parent.get("sharpe") or 0
    ic = parent.get("ic_mean")
    icir = parent.get("icir")
    turnover = parent.get("turnover")
    annual_ret = parent.get("annual_return")
    max_dd = parent.get("max_drawdown")
    long_ret = parent.get("long_return")
    short_ret = parent.get("short_return")
    classification = parent.get("classification", "unknown")
    notes = parent.get("diagnosis_notes", [])
    suggestions = parent.get("improvement_suggestions", [])

    lines = [f"### Parent {rank}: `{name}`"]
    lines.append(f"- **Expression**: `{expr}`")
    lines.append(f"- **Sharpe**: {sharpe:.4f} | **IC Mean**: {ic if ic is not None else 'N/A'}")
    lines.append(f"- **ICIR**: {icir if icir is not None else 'N/A'} | **Turnover**: {turnover if turnover is not None else 'N/A'}")
    lines.append(f"- **Annual Return**: {annual_ret if annual_ret is not None else 'N/A'} | **Max DD**: {max_dd if max_dd is not None else 'N/A'}")
    lines.append(f"- **Long Return**: {long_ret if long_ret is not None else 'N/A'} | **Short Return**: {short_ret if short_ret is not None else 'N/A'}")
    lines.append(f"- **Classification**: {classification}")
    if notes:
        lines.append(f"- **Diagnosis Notes**: {'; '.join(notes)}")
    if suggestions:
        lines.append(f"- **Improvement Suggestions**: {'; '.join(suggestions)}")
    return "\n".join(lines)


def _format_kb_context(kb: dict) -> str:
    """Format knowledge base insights for the LLM prompt."""
    lines = []

    # Field effectiveness
    field_eff = kb.get("field_effectiveness", {})
    if field_eff:
        total = sum(field_eff.values()) or 1
        field_pcts = {k: f"{v/total*100:.0f}%" for k, v in sorted(field_eff.items(), key=lambda x: -x[1])}
        lines.append("### Field Usage Distribution")
        lines.append(" | ".join(f"{k}: {v}" for k, v in field_pcts.items()))

    # Successful patterns (top 5 by Sharpe)
    successful = sorted(
        kb.get("successful_patterns", []),
        key=lambda x: x.get("avg_sharpe", 0),
        reverse=True,
    )[:5]
    if successful:
        lines.append("\n### Top Successful Patterns")
        for sp in successful:
            lines.append(f"- `{sp.get('pattern', '')[:80]}` — Sharpe {sp.get('avg_sharpe', 0):.3f} (seen {sp.get('times_seen', 1)}×)")

    # Failed patterns (top 5)
    failed = sorted(
        kb.get("failed_patterns", []),
        key=lambda x: x.get("times_failed", 0),
        reverse=True,
    )[:5]
    if failed:
        lines.append("\n### Recurring Failure Patterns")
        for fp in failed:
            lines.append(f"- `{fp.get('pattern', '')[:80]}` — failed {fp.get('times_failed', 1)}×")

    # Error log patterns
    error_log = kb.get("error_log", [])[-10:]
    if error_log:
        lines.append("\n### Recent Errors")
        for err in error_log[-5:]:
            lines.append(f"- `{err.get('name', '')}`: {'; '.join(err.get('notes', ['unknown error']))}")

    # High turnover structures
    high_to = kb.get("high_turnover_structures", [])[-5:]
    if high_to:
        lines.append("\n### High Turnover Patterns (TO > 0.8)")
        for ht in high_to:
            lines.append(f"- `{ht.get('name', '')}`: TO={ht.get('turnover', 0):.2f}")

    # Best factor history
    best_hist = kb.get("best_factor_history", [])
    if best_hist:
        lines.append("\n### Best Factor Progression")
        for bh in best_hist:
            lines.append(f"- Iter {bh.get('iteration', '?')}: `{bh.get('factor', '')}` — Sharpe {bh.get('sharpe', 0):.3f}")

    return "\n".join(lines)


def generate_transform_prompt(
    diagnosis: dict,
    kb: dict,
    query: str = "",
    num_parents: int = 3,
) -> str:
    """Generate a structured prompt asking the LLM to rank transformations.

    Args:
        diagnosis: Diagnosis output from diagnose.py.
        kb: Knowledge base dict.
        query: Original user query.
        num_parents: How many top parents to include.

    Returns:
        A markdown prompt string to feed to an LLM.
    """
    diagnostics = diagnosis.get("diagnostics", [])
    valid = [d for d in diagnostics if d.get("sharpe") is not None]
    valid.sort(key=lambda d: d.get("sharpe") or 0, reverse=True)
    top_parents = valid[:num_parents]

    lines = [
        "# Factor Evolution — Transformation Suggestion Request",
        "",
        "You are a quantitative researcher optimizing alpha factors for the ",
        "Chinese A-share market (CSI 300). You will be given parent factors ",
        "with their backtest diagnostics. Your task is to propose the **3-5 most",
        "promising semantic transformations** for each parent, ranked by expected",
        "Sharpe improvement.",
        "",
        "## ⚠️ CRITICAL RULES",
        "",
        "1. **Do NOT propose syntactic wrappers** — wrapping in `clip()`, `rank()`, ",
        "   or `ts_mean()` when the core signal is unchanged is WORTHLESS.",
        "2. **Propose SEMANTIC changes** — change the logic: combine fields, adjust ",
        "   weights, add complementary signals, change function families.",
        "3. **Be creative but valid** — every proposed expression must use ONLY the ",
        "   allowed 27 functions and 6 fields listed below.",
        "4. **Provide the EXACT modified expression** — no pseudocode, no placeholders.",
        "5. **Rationale is REQUIRED** — explain WHY the change should improve Sharpe/IC/turnover.",
        "",
        "---",
        "",
    ]

    if query:
        lines.append(f"## 📝 Original User Query\n\n> {query}\n")

    # Allowed functions and fields
    lines.append("## 🔧 Allowed Building Blocks\n")
    lines.append(f"**6 Fields**: {', '.join(sorted(ALLOWED_FIELDS))}\n")
    lines.append(f"**27 Functions**: {', '.join(sorted(ALLOWED_FUNCTIONS))}\n")

    # KB context
    kb_context = _format_kb_context(kb)
    if kb_context.strip():
        lines.append("## 📊 Knowledge Base Insights\n")
        lines.append(kb_context)
        lines.append("")

    # Parent profiles
    lines.append(f"## 🧬 Parent Factors (Top {num_parents} by Sharpe)\n")
    for i, parent in enumerate(top_parents):
        lines.append(_format_parent_profile(parent, i + 1))
        lines.append("")

    # Expected output format
    lines.append("## 📤 Expected Output Format\n")
    lines.append("Return a **JSON object** with this exact structure:\n")
    lines.append("```json")
    lines.append(json.dumps({
        "transforms": [
            {
                "parent": "parent_factor_name",
                "rank": 1,
                "name": "descriptive-transform-name",
                "expression": "exact_modified_expression_here",
                "rationale": "Why this should improve metrics...",
                "expected_impact": "+0.03 to +0.06 Sharpe, -0.05 turnover"
            }
        ],
        "meta": {
            "strategy_notes": "Overall strategy for this iteration...",
            "convergence_warning": "false/true — are we stuck in a local optimum?",
            "diversification_needed": "false/true — should we generate fresh seed factors?"
        }
    }, indent=2))
    lines.append("```\n")
    lines.append("Generate **3-5 transforms per parent**. Merge similar transforms across parents.")
    lines.append("**Return ONLY the JSON — no markdown, no explanations, no code fences.**")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Response Application
# ═══════════════════════════════════════════════════════════════════════════════

def apply_llm_response(
    response_path: str,
    diagnosis: dict,
) -> list[dict]:
    """Parse LLM response and convert to transform suggestions.

    Args:
        response_path: Path to the LLM's JSON response file.
        diagnosis: Current diagnosis for context (parent lookup).

    Returns:
        List of transform suggestion dicts compatible with generate_candidates.
    """
    resp = json.loads(Path(response_path).read_text(encoding="utf-8-sig"))

    # Support both direct array and {transforms: [...]} wrapper
    if isinstance(resp, list):
        transforms = resp
    elif isinstance(resp, dict):
        transforms = resp.get("transforms", [])
    else:
        transforms = []

    suggestions = []
    diagnostics = {d["name"]: d for d in diagnosis.get("diagnostics", [])}

    for t in transforms:
        parent_name = t.get("parent", "")
        parent = diagnostics.get(parent_name, {})
        expr = t.get("expression", "")

        if not expr:
            continue

        suggestions.append({
            "parent": parent_name,
            "parent_expression": parent.get("expression", ""),
            "rank": t.get("rank", len(suggestions) + 1),
            "name": f"{parent_name}_llm_{t.get('name', 'transform').replace(' ', '-')}",
            "expression": expr,
            "rationale": t.get("rationale", "LLM-suggested transformation"),
            "expected_impact": t.get("expected_impact", ""),
            "generation": "llm-transform",
            "transformation": t.get("name", "llm-suggested"),
            "description": f"LLM-suggested variant of {parent_name}: {t.get('rationale', '')[:100]}",
        })

    return suggestions


# ═══════════════════════════════════════════════════════════════════════════════
# KB Context Summary (for agents to feed into LLM calls)
# ═══════════════════════════════════════════════════════════════════════════════

def get_kb_context_for_llm(kb: dict) -> dict:
    """Extract a compact KB summary suitable for LLM context windows.

    Returns a dict with:
    - field_diversity: which fields are over/under used
    - top_patterns: top 5 successful patterns
    - avoid_patterns: patterns that repeatedly fail
    - plateau_warning: true if system is stuck
    - recommended_directions: suggested exploration vectors
    """
    field_eff = kb.get("field_effectiveness", {})
    total = sum(field_eff.values()) or 1

    # Field diversity analysis
    field_pcts = {k: v / total for k, v in field_eff.items()}
    overused = [k for k, v in field_pcts.items() if v > 0.25]
    underused = [k for k, v in field_pcts.items() if v < 0.08]

    # Successful patterns
    successful = sorted(
        kb.get("successful_patterns", []),
        key=lambda x: x.get("avg_sharpe", 0),
        reverse=True,
    )[:5]

    # Failed patterns (seen 2+ times)
    failed = [
        fp for fp in kb.get("failed_patterns", [])
        if fp.get("times_failed", 0) >= 2
    ]

    # Plateau detection
    best_hist = kb.get("best_factor_history", [])
    plateau_warning = False
    if len(best_hist) >= 3:
        recent_sharpes = [h.get("sharpe", 0) for h in best_hist[-3:]]
        if max(recent_sharpes) - min(recent_sharpes) < 0.005:
            plateau_warning = True

    # Recommended directions
    directions = []
    if "volume" in underused:
        directions.append("Explore volume-based signals — currently underexplored")
    if "amount" in underused:
        directions.append("Explore turnover/amount signals — completely unused")
    if "high" in overused and "low" in overused:
        directions.append("High/low range patterns saturated — try mean-reversion or momentum")
    if plateau_warning:
        directions.append("⚠️ PLATEAU DETECTED — generate fresh seed factors from new families")

    return {
        "field_diversity": {k: round(v, 3) for k, v in field_pcts.items()},
        "overused_fields": overused,
        "underused_fields": underused,
        "top_patterns": [{"expression": p.get("pattern", ""), "sharpe": p.get("avg_sharpe", 0)} for p in successful],
        "avoid_patterns": [fp.get("pattern", "") for fp in failed],
        "plateau_warning": plateau_warning,
        "iterations_completed": kb.get("iterations_completed", 0),
        "recommended_directions": directions,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-driven transformation suggestion engine."
    )
    parser.add_argument("--generate-prompt", action="store_true",
                        help="Generate a structured prompt for the LLM.")
    parser.add_argument("--apply-response", action="store_true",
                        help="Apply an LLM response to generate transform suggestions.")
    parser.add_argument("--kb-context", action="store_true",
                        help="Output a compact KB context summary for LLM consumption.")
    parser.add_argument("--diagnosis", type=str, default="",
                        help="Path to diagnosis JSON.")
    parser.add_argument("--knowledge", type=str, default="knowledge_base.json",
                        help="Path to knowledge base JSON.")
    parser.add_argument("--response", type=str, default="",
                        help="Path to LLM response JSON (for --apply-response).")
    parser.add_argument("--query", type=str, default="",
                        help="Original user input query.")
    parser.add_argument("--output", type=str, default="",
                        help="Output path.")
    parser.add_argument("--num-parents", type=int, default=3,
                        help="Number of top parents to include in prompt (default: 3).")
    args = parser.parse_args()

    if args.generate_prompt:
        if not args.diagnosis:
            print(json.dumps({"error": "--diagnosis required"}, ensure_ascii=False))
            sys.exit(1)

        diag = json.loads(Path(args.diagnosis).read_text(encoding="utf-8-sig"))
        kb = {}
        if Path(args.knowledge).is_file():
            kb = json.loads(Path(args.knowledge).read_text(encoding="utf-8-sig"))

        prompt = generate_transform_prompt(diag, kb, args.query, args.num_parents)

        out = args.output or str(_resolve_output("transform_prompt.md"))
        Path(out).write_text(prompt, encoding="utf-8")
        print(json.dumps({"status": "prompt_generated", "path": out, "char_count": len(prompt)}, ensure_ascii=False))

    elif args.apply_response:
        if not args.response:
            print(json.dumps({"error": "--response required"}, ensure_ascii=False))
            sys.exit(1)
        if not args.diagnosis:
            print(json.dumps({"error": "--diagnosis required"}, ensure_ascii=False))
            sys.exit(1)

        diag = json.loads(Path(args.diagnosis).read_text(encoding="utf-8-sig"))
        suggestions = apply_llm_response(args.response, diag)

        out = args.output or str(_resolve_output("transform_suggestions.json"))
        Path(out).write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "response_applied", "n_suggestions": len(suggestions), "path": out}, ensure_ascii=False))

    elif args.kb_context:
        kb = {}
        kb_path = Path(args.knowledge)
        if kb_path.is_file():
            kb = json.loads(kb_path.read_text(encoding="utf-8-sig"))

        context = get_kb_context_for_llm(kb)

        out = args.output
        if out:
            Path(out).write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(context, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
