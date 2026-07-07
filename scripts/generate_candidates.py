#!/usr/bin/env python3
"""Controlled variant generator for skill-factor-loop-evolve.

Selects the strongest current factors as parents and applies controlled
transformations (adjust lookback, change smoothing, add/remove clipping,
adjust normalization, combine, simplify, reduce turnover, create asymmetric
variants) with explicit rationale based on previous diagnostics.

Usage::

    python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge kb.json --output next.json
    python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge kb.json --output next.json --max-candidates 10
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import (  # noqa: E402
    TRANSFORMATION_RATIONALE_MAP,
    MIN_PARENTS,
    MAX_PARENTS,
    MIN_TRANSFORMS,
    MAX_TRANSFORMS,
    REDUCE_TURNOVER_THRESHOLD,
    LOW_TURNOVER_THRESHOLD,
    FLIP_SIGN_SHARPE_THRESHOLD,
    USE_LLM_TRANSFORMS,
    output_path as _resolve_output,
)
from llm_suggest import generate_transform_prompt  # noqa: E402
from parent_selection import select_parents  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# Transformation Application
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_factor_name(name: str) -> str:
    """Convert a generated factor name to snake_case."""
    safe = re.sub(r"[^0-9a-zA-Z_]+", "_", name).strip("_").lower()
    return safe or "factor"


def apply_transformation(
    parent: dict,
    transformation: str,
    factor_index: int,
) -> dict | None:
    """Apply a controlled transformation to a parent factor.

    Args:
        parent: Parent factor diagnostic dict.
        transformation: Transformation type from VALID_TRANSFORMATIONS.
        factor_index: Counter for naming.

    Returns:
        New factor dict or None if transformation is not applicable.
    """
    name = parent.get("name", "parent")
    expr = parent.get("expression", "")
    sharpe = parent.get("sharpe") or 0
    turnover = parent.get("turnover") or 0

    rationale = TRANSFORMATION_RATIONALE_MAP.get(transformation, "Diagnostic-driven improvement")

    new_factor = {
        "name": _safe_factor_name(f"{name}_v{factor_index}_{transformation}"),
        "expression": expr,
        "description": f"Variant of {name}: {rationale}",
        "rationale": rationale,
        "generation": f"variant-{transformation}",
        "parent": name,
        "transformation": transformation,
    }

    # Apply transformation logic to modify the expression
    modified_expr = _modify_expression(expr, transformation, {"sharpe": sharpe, "turnover": turnover})
    if modified_expr:
        new_factor["expression"] = modified_expr
        new_factor["description"] = f"Variant of {name}: {transformation} — {rationale}"
    else:
        # If no modification possible, still keep the factor but mark it
        new_factor["description"] += " (no structural change possible)"

    return new_factor


def _strip_outer_function(expression: str, func_name: str) -> str | None:
    """Strip the outermost call to ``func_name(...)`` from an expression.

    Uses parenthesis counting to correctly handle nested function calls.
    Returns the first argument (inner expression) plus any trailing text
    after the function call, or None if ``func_name`` is not found.

    Example:
        ``decay_linear(returns(close, 20) / max(ts_std(close, 60), 1e-8), 20)``
        → ``returns(close, 20) / max(ts_std(close, 60), 1e-8)``
    """
    prefix = func_name + "("
    idx = expression.find(prefix)
    if idx == -1:
        return None
    start = idx + len(prefix)
    depth = 1
    for i in range(start, len(expression)):
        if expression[i] == "(":
            depth += 1
        elif expression[i] == ")":
            depth -= 1
            if depth == 0:
                # Found matching closing paren of the full function call
                full_args = expression[start:i]
                # Find the first comma at depth 0 to split first arg from rest
                arg_depth = 0
                split_at = len(full_args)  # default: no split
                for j, ch in enumerate(full_args):
                    if ch == "(":
                        arg_depth += 1
                    elif ch == ")":
                        arg_depth -= 1
                    elif ch == "," and arg_depth == 0:
                        split_at = j
                        break
                inner = full_args[:split_at].strip()
                rest = expression[i + 1:]
                return inner + rest
    return None


def _modify_expression(
    expression: str,
    transformation: str,
    metrics: dict,
) -> str | None:
    """Attempt to modify an expression based on the transformation type.

    Returns modified expression or None if no modification needed/possible.
    """
    if transformation == "adjust-lookback":
        # Try to increase or decrease rolling window parameters by ±50%
        def _adjust_window(match):
            func = match.group(1)
            first_arg = match.group(2)
            n = int(match.group(3))
            if n <= 10:
                new_n = min(n * 2, 252)
            elif n >= 120:
                new_n = max(n // 2, 2)
            else:
                # Randomly go up or down
                new_n = int(n * 1.5) if n < 60 else int(n * 0.67)
            return f"{func}({first_arg}, {new_n})"

        new_expr = re.sub(
            r'(ts_\w+|correlation|covariance|decay_linear|delay|delta|adv)\s*\((.+),\s*(\d+)\s*\)',
            _adjust_window,
            expression,
        )
        # Also adjust returns(x, n)
        new_expr = re.sub(
            r'returns\s*\(([^,]+),\s*(\d+)\)',
            lambda m: f"returns({m.group(1).strip()}, {max(2, int(m.group(2)) * 2 if int(m.group(2)) <= 10 else int(int(m.group(2)) * 0.67))})",
            new_expr,
        )
        if new_expr != expression:
            return new_expr

    elif transformation == "adjust-smoothing":
        # Wrap in decay_linear or add ts_mean
        if "decay_linear" not in expression and "ts_mean" not in expression:
            n = 20
            return f"decay_linear({expression}, {n})"
        elif "decay_linear" in expression:
            # Remove smoothing — use paren-aware stripping
            new_expr = _strip_outer_function(expression, "decay_linear")
            if new_expr and new_expr != expression:
                return new_expr

    elif transformation == "adjust-clipping":
        # Add clip
        if "clip" not in expression:
            return f"clip({expression}, -3, 3)"
        else:
            # Remove clip — use paren-aware stripping
            new_expr = _strip_outer_function(expression, "clip")
            if new_expr and new_expr != expression:
                return new_expr

    elif transformation == "adjust-normalization":
        # Switch between rank, zscore, scale
        if "rank(" in expression and "zscore(" not in expression:
            return expression.replace("rank(", "zscore(")
        elif "zscore(" in expression:
            return expression.replace("zscore(", "rank(")
        elif "scale(" in expression:
            return expression.replace("scale(", "zscore(")
        else:
            return f"rank({expression})"

    elif transformation == "simplify":
        # Remove one level of nesting if too complex
        if expression.count("(") > 3:
            # Try to remove the outermost function
            outer_match = re.match(r'(\w+)\((.+)\)$', expression.strip())
            if outer_match:
                inner = outer_match.group(2)
                # Only simplify if inner is also a function call
                if re.match(r'\w+\(.+\)', inner):
                    return inner
        return None

    elif transformation == "reduce-turnover":
        # Increase smoothing by wrapping in ts_mean with longer window
        return f"ts_mean({expression}, 20)"

    elif transformation == "long-only":
        if "clip" not in expression:
            return f"clip({expression}, 0, 1e8)"
        return None

    elif transformation == "short-only":
        if "clip" not in expression:
            return f"clip({expression}, -1e8, 0)"
        return None

    elif transformation == "asymmetric":
        # Weight long side more
        if "clip" not in expression:
            return f"clip({expression}, 0, 1e8) * 1.5 + clip({expression}, -1e8, 0) * 0.5"
        return None

    elif transformation == "flip-sign":
        # Negate the entire expression to invert the factor direction
        return f"-({expression})"

    return None


def determine_transformations(
    parent: dict,
    min_transforms: int = 1,
    max_transforms: int = 5,
) -> list[str]:
    """Determine which transformations are applicable to a parent factor.

    Based on the factor's metrics and diagnosis notes.
    Respects min/max transforms per parent from config.
    """
    diagnostics = parent.get("improvement_suggestions", [])
    applicable = []

    # Flip sign FIRST — most impactful transform for negative Sharpe
    sharpe_val = parent.get("sharpe") or 0
    if sharpe_val < FLIP_SIGN_SHARPE_THRESHOLD:
        applicable.append("flip-sign")

    turnover = parent.get("turnover", 0)
    if turnover > REDUCE_TURNOVER_THRESHOLD:
        applicable.extend(["reduce-turnover", "adjust-smoothing"])
    if turnover < LOW_TURNOVER_THRESHOLD:
        applicable.append("adjust-lookback")

    # Always try lookback adjustment and normalization
    applicable.append("adjust-lookback")
    applicable.append("adjust-normalization")

    # For promising factors, try clipping
    applicable.append("adjust-clipping")

    # For factors with suggestions
    for s in diagnostics:
        if "turnover" in s.lower():
            applicable.append("reduce-turnover")
        if "simplify" in s.lower():
            applicable.append("simplify")
        if "smoothing" in s.lower() or "lookback" in s.lower():
            applicable.append("adjust-lookback")
            applicable.append("adjust-smoothing")

    # Directional transforms
    long_ret = parent.get("long_return", 0)
    short_ret = parent.get("short_return", 0)

    if long_ret is not None and short_ret is not None:
        if long_ret > 0 and short_ret < long_ret * 0.3:
            applicable.append("long-only")
        if short_ret < 0 and abs(short_ret) > abs(long_ret) * 1.5:
            applicable.append("short-only")

    applicable.append("asymmetric")

    # Deduplicate while preserving order
    seen = set()
    result = []
    for t in applicable:
        if t not in seen:
            seen.add(t)
            result.append(t)

    # Clamp to [min_transforms, max_transforms]
    result = result[:max_transforms]
    # Ensure we have at least min_transforms (pad with safe defaults if needed).
    # Keep this finite: some parents already contain every default transform.
    defaults = [
        "adjust-lookback",
        "adjust-normalization",
        "adjust-clipping",
        "reduce-turnover",
        "adjust-smoothing",
        "flip-sign",
        "simplify",
        "long-only",
        "short-only",
        "asymmetric",
    ]
    while len(result) < min_transforms:
        added = False
        for d in defaults:
            if d not in seen and len(result) < min_transforms:
                result.append(d)
                seen.add(d)
                added = True
            if len(result) >= min_transforms:
                break
        if not added:
            break

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Main Generator
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_expr(expr: str) -> str:
    """Normalize an expression for comparison: strip whitespace, remove outer parens."""
    return expr.strip().replace(" ", "").strip("()")


def _infer_transformation_tag(
    new_expr: str,
    parent_expr: str,
    rationale: str,
    suggestion: dict,
) -> str:
    """Infer a descriptive transformation tag from the LLM suggestion.

    Examines the expression change and rationale text to map to the closest
    transformation from the catalog, or derives a custom descriptive tag.
    Never returns the generic ``llm-suggested``.
    """
    # 1) If LLM explicitly provided a transformation tag, use it
    explicit = suggestion.get("transformation", "")
    if explicit and explicit != "llm-suggested":
        return explicit

    rationale_lower = rationale.lower()
    new_norm = _normalize_expr(new_expr)
    parent_norm = _normalize_expr(parent_expr)

    # 2) Sign flip: expression is negated version of parent
    if new_norm == _normalize_expr(f"-({parent_expr})") or new_norm.startswith("-"):
        # Check if the core expression is just negated
        stripped_new = new_norm.lstrip("-")
        if stripped_new == parent_norm or stripped_new.startswith(parent_norm):
            return "flip-sign"

    # 3) Smoothing / lookback: wrapped in ts_mean, decay_linear, ts_sum
    smoothing_funcs = ["ts_mean", "decay_linear", "ts_std", "ts_zscore", "ts_rank"]
    for sf in smoothing_funcs:
        if sf in new_expr.lower() and sf not in parent_expr.lower():
            # Check if it's fundamentally about smoothing
            if any(w in rationale_lower for w in ["smooth", "reduce noise", "rolling", "lookback"]):
                return "adjust-smoothing"
            return "adjust-lookback"

    # 4) Normalization change: different normalizer field
    normalizer_fields = {"volume", "amount", "high - low", "high-low"}
    new_norm_field = None
    parent_norm_field = None
    for nf in normalizer_fields:
        nf_norm = nf.replace(" - ", "-").replace(" ", "")
        if f"max({nf_norm}" in new_norm or f"max({nf}" in new_expr.lower():
            new_norm_field = nf
        if f"max({nf_norm}" in parent_norm or f"max({nf}" in parent_expr.lower():
            parent_norm_field = nf
    if new_norm_field and parent_norm_field and new_norm_field != parent_norm_field:
        return "adjust-normalization"

    # 5) Combine factors: contains "+" combining two distinct signal terms
    if "+" in new_expr and "+" not in parent_expr:
        if any(w in rationale_lower for w in ["combin", "add ", "blend", "plus", "diversif"]):
            return "combine-factors"

    # 6) Clipping added
    if "clip" in new_expr.lower() and "clip" not in parent_expr.lower():
        return "adjust-clipping"

    # 7) Reduce turnover / directional
    if any(w in rationale_lower for w in ["turnover", "trading cost"]):
        return "reduce-turnover"
    if any(w in rationale_lower for w in ["long-only", "long only"]):
        return "long-only"
    if any(w in rationale_lower for w in ["short-only", "short only"]):
        return "short-only"
    if any(w in rationale_lower for w in ["asymmetric"]):
        return "asymmetric"
    if any(w in rationale_lower for w in ["simplif", "remove"]):
        return "simplify"

    # 8) Cumulative / sum aggregation
    if "ts_sum" in new_expr.lower() and "ts_sum" not in parent_expr.lower():
        return "adjust-aggregation"

    # 9) New field or fundamentally new construction
    new_fields = {f for f in ["open", "high", "low", "close", "volume", "amount"] if f in new_expr.lower()}
    parent_fields = {f for f in ["open", "high", "low", "close", "volume", "amount"] if f in parent_expr.lower()}
    if new_fields != parent_fields:
        new_only = new_fields - parent_fields
        if new_only:
            return f"introduce-{'-'.join(sorted(new_only))}"

    # 10) Fallback: extract key concept from rationale
    keywords = [
        ("reversal", "reversal"),
        ("momentum", "momentum"),
        ("gap", "gap-signal"),
        ("cumulative", "cumulative"),
        ("acceleration", "acceleration"),
        ("revert", "reversal"),
        ("unflip", "unflip"),
        ("flip", "flip-sign"),
        ("smooth", "adjust-smoothing"),
        ("normaliz", "adjust-normalization"),
        ("combine", "combine-factors"),
        ("range", "introduce-range"),
        ("amount", "introduce-amount"),
    ]
    for keyword, tag in keywords:
        if keyword in rationale_lower:
            return tag

    return "semantic-transform"


def _apply_single_llm_transform(
    suggestion: dict,
    parent_lookup: dict[str, dict],
) -> dict | None:
    """Convert an LLM transform suggestion into a candidate factor dict.

    Validates that the suggested expression is non-empty and different
    from the parent. Performs basic sanity checks.
    """
    expr = suggestion.get("expression", "").strip()
    if not expr:
        return None

    parent_name = suggestion.get("parent", "")
    parent = parent_lookup.get(parent_name, {})
    parent_expr = parent.get("expression", "")

    # Skip if expression is identical to parent (normalize whitespace for comparison)
    if _normalize_expr(expr) == _normalize_expr(parent_expr):
        return None

    name = _safe_factor_name(suggestion.get("name", f"{parent_name}_llm_variant"))
    rationale = suggestion.get("rationale", "LLM-driven transformation")

    # Use LLM-provided transformation tag directly; infer only as fallback
    transformation = suggestion.get("transformation", "")
    if not transformation or transformation == "llm-suggested":
        transformation = _infer_transformation_tag(expr, parent_expr, rationale, suggestion)
        print(f"[WARN] LLM suggestion '{name}' missing 'transformation' field — inferred '{transformation}'.", file=sys.stderr)

    return {
        "name": name,
        "expression": expr,
        "description": suggestion.get("description", f"LLM-suggested variant of {parent_name}"),
        "rationale": rationale,
        "expected_impact": suggestion.get("expected_impact", ""),
        "generation": "llm-transform",
        "parent": parent_name,
        "transformation": transformation,
    }


def _latest_llm_suggestions(payload: object) -> list[dict]:
    """Read current suggestions from old list or new history payloads."""
    if isinstance(payload, list):
        return [s for s in payload if isinstance(s, dict)]

    if not isinstance(payload, dict):
        return []

    latest = payload.get("latest_suggestions")
    if isinstance(latest, list):
        return [s for s in latest if isinstance(s, dict)]

    history = payload.get("suggestion_history")
    if isinstance(history, list):
        for entry in reversed(history):
            if not isinstance(entry, dict):
                continue
            suggestions = entry.get("suggestions")
            if isinstance(suggestions, list):
                return [s for s in suggestions if isinstance(s, dict)]

    suggestions = payload.get("suggestions")
    if isinstance(suggestions, list):
        return [s for s in suggestions if isinstance(s, dict)]

    return []


def _write_missing_llm_prompt(
    diagnosis: dict,
    knowledge_base: dict,
    output_dir: Path,
    query: str,
    num_parents: int,
) -> Path:
    """Write the LLM transform prompt for the agent to complete."""
    prompt_path = output_dir / "transform_prompt.md"
    prompt = generate_transform_prompt(
        diagnosis,
        knowledge_base,
        query=query,
        num_parents=num_parents,
    )
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def generate_candidates(
    diagnosis: dict,
    knowledge_base: dict,
    max_candidates: int = 12,
    min_parents: int = 1,
    max_parents: int = 3,
    min_transforms: int = 1,
    max_transforms: int = 5,
    llm_suggestions: list[dict] | None = None,
    use_active_kb: bool = True,
) -> list[dict]:
    """Generate the next batch of factor candidates.

    Args:
        diagnosis: Diagnosis output from diagnose.py.
        knowledge_base: Current knowledge base.
        max_candidates: Maximum number of candidates to generate.
        min_parents: Minimum parent factors to select.
        max_parents: Maximum parent factors to select.
        min_transforms: Minimum transformations per parent.
        max_transforms: Maximum transformations per parent.
        llm_suggestions: Optional LLM-suggested transforms (bypasses rule-based).
        use_active_kb: Whether to apply active KB diversity boosts.

    Returns:
        List of new factor candidates.
    """
    parents = select_parents(
        diagnosis,
        max_parents=max_parents,
        min_parents=min_parents,
        knowledge_base=knowledge_base,
        use_active_kb=use_active_kb,
    )
    candidates = []
    factor_index = 0
    used_llm = False

    # ── LLM-Driven Path ───────────────────────────────────────────────
    if llm_suggestions:
        used_llm = True
        parent_lookup = {p["name"]: p for p in parents}
        # Also include all diagnostics for parent lookup
        for d in diagnosis.get("diagnostics", []):
            if d["name"] not in parent_lookup:
                parent_lookup[d["name"]] = d

        # Sort LLM suggestions by rank
        llm_suggestions.sort(key=lambda s: s.get("rank", 99))

        for suggestion in llm_suggestions:
            if len(candidates) >= max_candidates:
                break
            new_factor = _apply_single_llm_transform(suggestion, parent_lookup)
            if new_factor:
                candidates.append(new_factor)
                factor_index += 1

        # If LLM didn't give enough candidates, keep what we have — no rule-based fallback
        if len(candidates) < min_parents:
            print(f"[WARN] LLM produced only {len(candidates)} candidates (< {min_parents}). Proceeding with available candidates.", file=sys.stderr)

    # ── Rule-Based Path (original logic) ──────────────────────────────
    if not used_llm:
        for parent in parents:
            transformations = determine_transformations(
                parent,
                min_transforms=min_transforms,
                max_transforms=max_transforms,
            )

            for trans in transformations:
                if len(candidates) >= max_candidates:
                    break
                new_factor = apply_transformation(parent, trans, factor_index)
                if new_factor:
                    candidates.append(new_factor)
                    factor_index += 1

    # Static fallback only: if rule-based transforms did not fill the batch,
    # try combining low-correlation parents. LLM mode should remain LLM-only.
    if not used_llm and len(candidates) < max_candidates and len(parents) >= 2:
        for i in range(len(parents)):
            for j in range(i + 1, len(parents)):
                if len(candidates) >= max_candidates:
                    break
                p1 = parents[i]
                p2 = parents[j]
                # Check correlation
                too_correlated = False
                for key, corr in diagnosis.get("correlations", {}).items():
                    if p1["name"] in key and p2["name"] in key and corr > 0.3:
                        too_correlated = True
                        break
                if not too_correlated:
                    candidates.append({
                        "name": _safe_factor_name(f"{p1['name']}_comb_{p2['name']}"),
                        "expression": f"zscore({p1.get('expression', '')}) + zscore({p2.get('expression', '')})",
                        "description": f"Combination of {p1['name']} and {p2['name']}",
                        "rationale": "Both promising, low correlation — combined signal",
                        "generation": "variant-combine-factors",
                        "parent": f"{p1['name']},{p2['name']}",
                        "transformation": "combine-factors",
                    })
                    factor_index += 1

    # Deduplicate by name
    seen_names = set()
    unique = []
    for c in candidates:
        if c["name"] not in seen_names:
            seen_names.add(c["name"])
            unique.append(c)

    return unique


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate next batch of factor candidates via controlled transformations."
    )
    parser.add_argument("--diagnosis", type=str, required=True,
                        help="Path to diagnosis JSON.")
    parser.add_argument("--knowledge", type=str, required=True,
                        help="Path to knowledge base JSON.")
    parser.add_argument("--output", type=str, default="",
                        help="Output path for new candidates (default: output/<run-id>/next_candidates.json).")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Run identifier. Auto-generated timestamp if not given.")
    parser.add_argument("--max-candidates", type=int, default=12,
                        help="Maximum candidates to generate (default: 12).")
    parser.add_argument("--min-parents", type=int, default=MIN_PARENTS,
                        help=f"Minimum parents to select (default from config: {MIN_PARENTS}).")
    parser.add_argument("--max-parents", type=int, default=MAX_PARENTS,
                        help=f"Maximum parents to select (default from config: {MAX_PARENTS}).")
    parser.add_argument("--min-transforms", type=int, default=MIN_TRANSFORMS,
                        help=f"Minimum transformations per parent (default from config: {MIN_TRANSFORMS}).")
    parser.add_argument("--max-transforms", type=int, default=MAX_TRANSFORMS,
                        help=f"Maximum transformations per parent (default from config: {MAX_TRANSFORMS}).")
    parser.add_argument("--query", type=str, default="",
                        help="Original user input query that initiated this factor evolution run.")
    parser.add_argument("--use-llm", action="store_true",
                        help="Force LLM-driven transform suggestions (requires --llm-suggestions). Overrides config.")
    parser.add_argument("--no-llm", action="store_true",
                        help="Force static rule-based transforms, even when config enables LLM transforms.")
    parser.add_argument("--llm-suggestions", type=str, default="",
                        help="Path to LLM transform suggestions JSON (from llm_suggest.py --apply-response).")
    parser.add_argument("--llm-response", type=str, default="",
                        help="Path to a JSON file with LLM transform suggestions (direct format: array of {parent, expression, rationale, ...}). Use this to bypass the prompt/response file cycle.")
    parser.add_argument("--no-active-kb", action="store_true",
                        help="Disable active knowledge base diversity boosts in parent selection.")
    args = parser.parse_args()

    diag_path = Path(args.diagnosis)
    kb_path = Path(args.knowledge)

    if not diag_path.is_file():
        print(json.dumps({"error": f"File not found: {args.diagnosis}"}, ensure_ascii=False))
        sys.exit(1)
    if not kb_path.is_file():
        print(json.dumps({"error": f"File not found: {args.knowledge}"}, ensure_ascii=False))
        sys.exit(1)

    diagnosis = json.loads(diag_path.read_text(encoding="utf-8-sig"))
    kb = json.loads(kb_path.read_text(encoding="utf-8-sig"))

    if args.use_llm and args.no_llm:
        print(json.dumps({"error": "Use only one of --use-llm or --no-llm."}, ensure_ascii=False))
        sys.exit(1)

    # LLM is config-driven by default. Static transforms require --no-llm
    # or config.json transformations.use_llm_transforms=false.
    use_llm = (args.use_llm or USE_LLM_TRANSFORMS) and not args.no_llm
    default_output_path = None

    # ── Load LLM suggestions ────────────────────────────────────────
    llm_suggestions = None
    if use_llm:
        # Priority 1: --llm-response (direct JSON from agent/LLM)
        llm_path = args.llm_response or args.llm_suggestions
        if not llm_path:
            # Auto-detect: look for transform_suggestions.json in output dir
            if args.output:
                out_dir_guess = Path(args.output).parent
            else:
                default_output_path = _resolve_output("next_candidates.json")
                out_dir_guess = default_output_path.parent
            auto_path = out_dir_guess / "transform_suggestions.json"
            if auto_path.is_file():
                llm_path = str(auto_path)

        if llm_path and Path(llm_path).is_file():
            llm_payload = json.loads(Path(llm_path).read_text(encoding="utf-8-sig"))
            llm_suggestions = _latest_llm_suggestions(llm_payload)
            print(f"[INFO] Loaded {len(llm_suggestions)} LLM transform suggestions from {llm_path}", file=sys.stderr)
        else:
            prompt_path = _write_missing_llm_prompt(
                diagnosis,
                kb,
                out_dir_guess,
                query=args.query,
                num_parents=args.max_parents,
            )
            print(json.dumps({
                "status": "llm_suggestions_required",
                "message": (
                    "LLM transforms are enabled. The agent should read transform_prompt.md, "
                    "synthesize semantic transformations, save them as JSON, and re-run with "
                    "--llm-response <file>."
                ),
                "prompt_path": str(prompt_path),
                "next_steps": [
                    "1. Read transform_prompt.md",
                    "2. Synthesize 3-5 semantic transformations per parent as a JSON array",
                    "3. Save to llm_response.json in the output directory",
                    "4. Re-run: python scripts/generate_candidates.py --diagnosis ... --knowledge ... --llm-response llm_response.json",
                ],
                "static_fallback": "Use --no-llm only when you intentionally want static rule-based transforms.",
            }, ensure_ascii=False, indent=2))
            sys.exit(2)

    use_active_kb = not args.no_active_kb

    candidates = generate_candidates(
        diagnosis, kb,
        max_candidates=args.max_candidates,
        min_parents=args.min_parents,
        max_parents=args.max_parents,
        min_transforms=args.min_transforms,
        max_transforms=args.max_transforms,
        llm_suggestions=llm_suggestions,
        use_active_kb=use_active_kb,
    )

    # ── Get the actual mutation parents (same as used by generate_candidates) ─
    mutation_parents = select_parents(
        diagnosis,
        max_parents=args.max_parents,
        min_parents=args.min_parents,
        knowledge_base=kb,
        use_active_kb=use_active_kb,
    )
    mutation_parent_ids = {p["name"] for p in mutation_parents}

    out = args.output if args.output else str(default_output_path or _resolve_output("next_candidates.json"))
    Path(out).write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Save evolution tree ───────────────────────────────────────────────
    out_dir = Path(out).parent
    evo_path = out_dir / "candidate_evolution.json"

    # Load existing evolution if any
    if evo_path.is_file():
        evo = json.loads(evo_path.read_text(encoding="utf-8-sig"))
    else:
        evo = {"nodes": [], "edges": [], "run_iteration": 0}

    # ── Preserve or set the original user query ─────────────────────
    if args.query and not evo.get("query"):
        evo["query"] = args.query

    # ── Run-local iteration counter (NOT the global KB counter) ─────────
    # Each call to generate_candidates advances one generation:
    #   parents belong to the just-completed backtest iteration,
    #   candidates are for the NEXT iteration.
    current_iter = evo.get("run_iteration", 0) + 1
    evo["run_iteration"] = current_iter

    existing_ids = {n["id"] for n in evo["nodes"]}

    # Mark ONLY the parents that were actually used for mutation (max 3)
    for parent in mutation_parents:
        pid = parent["name"]
        p_cls = parent.get("classification", "")
        p_sharpe = parent.get("sharpe") or 0
        p_to = parent.get("turnover") or 0
        # Simple selection reason
        parts = [f"S={p_sharpe:.2f}"]
        if p_to > 0.85:
            parts.append(f"TO={p_to:.2f}")
        reason = f"selected: {', '.join(parts)}"
        if pid not in existing_ids:
            evo["nodes"].append({
                "id": pid,
                "expression": parent.get("expression", pid),
                "label": parent.get("expression", pid)[:100],
                "sharpe": p_sharpe,
                "iteration": current_iter,
                "classification": p_cls,
                "is_parent": True,
                "selection_reason": reason,
            })
            existing_ids.add(pid)
        else:
            for n in evo["nodes"]:
                if n["id"] == pid:
                    n["is_parent"] = True
                    n["selection_reason"] = reason
                    break

    # Add new candidates as nodes and edges
    for c in candidates:
        cid = c["name"]
        if cid not in existing_ids:
            evo["nodes"].append({
                "id": cid,
                "expression": c.get("expression", cid),
                "label": c.get("expression", cid)[:100],
                "sharpe": 0,  # will be updated after backtest
                "iteration": current_iter + 1,
                "classification": "",
            })
            existing_ids.add(cid)
        parent_id = c.get("parent", "")
        transformation = c.get("transformation", "")
        rationale = c.get("rationale", "")
        if parent_id:
            edge_key = f"{parent_id}__{cid}"
            if not any(e["from"] == parent_id and e["to"] == cid for e in evo["edges"]):
                evo["edges"].append({
                    "from": parent_id,
                    "to": cid,
                    "transformation": transformation,
                    "rationale": rationale,
                })

    evo_path.write_text(
        json.dumps(evo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "n_candidates": len(candidates),
        "output": out,
        "candidates": candidates,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
