#!/usr/bin/env python3
"""Optimization loop coordinator for skill-factor-loop-evolve.

Generates the final summary after all iterations: optimization log,
final alpha library, best factors, rejected factors, useful patterns,
failed patterns, and a recommendation on whether the optimized set
is worth keeping.

Usage::

    python scripts/optimizer.py --summary --output final_summary.json
    python scripts/optimizer.py --summary --knowledge kb.json --output final_summary.json
    python scripts/optimizer.py --check-stall --diagnosis diag.json --knowledge kb.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import (  # noqa: E402
    STALL_ITERATIONS,
    DIMINISHING_RETURN_THRESHOLD,
    MIN_ITERATIONS,
    MAX_ITERATIONS,
    WORTH_KEEPING_SHARPE_THRESHOLD,
    TAG_HIGH_SHARPE,
    TAG_LOW_SHARPE_ABS,
    TAG_HIGH_IC_ABS,
    TAG_LOW_IC_ABS,
    TAG_HIGH_TURNOVER,
    TAG_LOW_TURNOVER,
    TAG_HIGH_DRAWDOWN,
    output_path as _resolve_output,
)


def check_stopping_criteria(
    diagnosis: dict,
    knowledge_base: dict,
    max_iterations: int = 5,
) -> dict:
    """Check if the optimization loop should stop.

    Args:
        diagnosis: Current diagnosis output.
        knowledge_base: Current knowledge base.
        max_iterations: Max iterations allowed.

    Returns:
        Dict with should_stop, reason, and details.
    """
    iterations = knowledge_base.get("iterations_completed", 0)
    best_history = knowledge_base.get("best_factor_history", [])

    # Check 1: Max iterations
    if iterations >= max_iterations:
        return {
            "should_stop": True,
            "reason": f"Max iterations reached ({iterations}/{max_iterations})",
        }

    # Check 2: No valid candidates
    if diagnosis.get("n_total", 0) == diagnosis.get("n_invalid", 0):
        return {
            "should_stop": True,
            "reason": "No valid candidates remain",
        }

    # Check 3: Improvement stall
    if len(best_history) >= STALL_ITERATIONS:
        recent_sharpes = [h["sharpe"] for h in best_history[-STALL_ITERATIONS:]]
        if len(set(round(s, 4) for s in recent_sharpes)) == 1 or max(recent_sharpes) - min(recent_sharpes) < 0.001:
            return {
                "should_stop": True,
                "reason": f"Sharpe unchanged for {STALL_ITERATIONS} consecutive iterations",
            }

    # Check 4: Diminishing returns
    if len(best_history) >= 2:
        last_two = best_history[-2:]
        improvement = last_two[1]["sharpe"] - last_two[0]["sharpe"]
        if improvement < DIMINISHING_RETURN_THRESHOLD and improvement >= 0:
            return {
                "should_stop": True,
                "reason": f"Diminishing returns: Sharpe improvement {improvement:.4f} < {DIMINISHING_RETURN_THRESHOLD}",
            }

    return {"should_stop": False, "reason": "Continue optimization"}


def generate_summary(knowledge_path: str, output_path: str) -> dict:
    """Generate the final optimization summary.

    Args:
        knowledge_path: Path to knowledge base JSON.
        output_path: Path to save the summary.

    Returns:
        Final summary dict.
    """
    kb_path = Path(knowledge_path)
    if not kb_path.is_file():
        return {"error": f"Knowledge base not found: {knowledge_path}"}

    kb = json.loads(kb_path.read_text(encoding="utf-8-sig"))

    iterations = kb.get("iterations_completed", 0)
    best_history = kb.get("best_factor_history", [])
    successful = kb.get("successful_patterns", [])
    failed = kb.get("failed_patterns", [])

    # Build final alpha library from successful patterns (sorted by actual Sharpe)
    final_library = sorted(successful, key=lambda x: x.get("avg_sharpe", 0), reverse=True)

    # Worth keeping?
    worth_keeping = False
    rationale = ""
    if len(final_library) > 0:
        best_sharpe = final_library[0].get("avg_sharpe", 0)
        if best_sharpe >= WORTH_KEEPING_SHARPE_THRESHOLD:
            worth_keeping = True
            rationale = f"Top factor has Sharpe {best_sharpe:.2f} (≥ {WORTH_KEEPING_SHARPE_THRESHOLD} threshold). "
        else:
            rationale = f"Top factor Sharpe {best_sharpe:.2f} is below {WORTH_KEEPING_SHARPE_THRESHOLD} threshold. "
    else:
        rationale = "No factors survived optimization. "

    if iterations >= 3 and len(best_history) >= 2:
        first_sharpe = best_history[0].get("sharpe", 0)
        last_sharpe = best_history[-1].get("sharpe", 0)
        improvement = last_sharpe - first_sharpe
        if improvement > 0.1:
            worth_keeping = True
            rationale += f"Sharpe improved from {first_sharpe:.2f} to {last_sharpe:.2f} over {iterations} iterations."
        elif improvement > -0.1:
            rationale += f"Sharpe stable ({first_sharpe:.2f} → {last_sharpe:.2f})."
        else:
            rationale += "No improvement over iterations."

    # Build optimization log
    optimization_log = []
    for i, h in enumerate(best_history):
        optimization_log.append({
            "iteration": h.get("iteration", i + 1),
            "best_factor": h.get("factor"),
            "best_sharpe": h.get("sharpe"),
        })

    # Best factors: top 5 by actual Sharpe, concise
    best_factors = []
    for p in final_library[:5]:
        best_factors.append({
            "factor": p.get("pattern", ""),
            "sharpe": p.get("avg_sharpe", 0),
        })

    # ── Pareto frontier ──────────────────────────────────────────────
    output_dir = Path(output_path).parent
    all_factors = _collect_all_factors(output_dir)
    pareto_factors = _compute_pareto_frontier(all_factors)
    pareto_summary = []
    for pf in pareto_factors[:10]:
        pareto_summary.append({
            "factor": pf.get("expression", pf.get("name", "")),
            "sharpe": pf.get("sharpe", 0),
            "turnover": pf.get("turnover", 0),
            "max_drawdown": pf.get("max_drawdown", 0),
            "annual_return": pf.get("annual_return", 0),
            "ic_mean": pf.get("ic_mean", 0),
        })

    summary = {
        "iterations": iterations,
        "optimization_log": optimization_log,
        "best_factors": best_factors,
        "pareto_frontier": pareto_summary,
        "worth_keeping": worth_keeping,
        "worth_keeping_rationale": rationale,
        "query": _load_query(Path(output_path).parent),
        "evolution_diagram": _build_evolution_diagram(
            kb, best_factors, best_history,
            output_dir=str(Path(output_path).parent),
        ),
        "active_config": _load_active_config(),
    }

    Path(output_path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    out_dir = Path(output_path).parent

    # Also copy config.json into output for reproducibility
    cfg_src = Path(__file__).resolve().parent.parent / "config.json"
    cfg_dst = out_dir / "config.json"
    if cfg_src.is_file():
        cfg_dst.write_text(cfg_src.read_text(encoding="utf-8"))

    # ── Clean up intermediate files (per output contract) ──────────────
    _cleanup_intermediate_files(out_dir)

    return summary


def _compute_filtered_top_factors(
    output_dir: Path,
    n_top: int = 10,
) -> list[dict]:
    """Compute top N factors from all backtest results.

    Sorts by Sharpe descending, removes only exact expression duplicates.
    Returns top N factors with full metrics, sorted by Sharpe descending.
    """
    bt_all_path = output_dir / "backtest_results_all.json"
    if not bt_all_path.is_file():
        return []

    all_bt = json.loads(bt_all_path.read_text(encoding="utf-8-sig"))

    # Collect all factor results across iterations
    all_results: list[dict] = []

    iterations = all_bt.get("iterations", [all_bt])
    for it in iterations:
        iter_num = it.get("iteration", 1)
        for fr in it.get("factor_results", it.get("results", [])):
            if "error" in fr or fr.get("sharpe") is None:
                continue
            fr["_iteration"] = fr.get("_iteration", iter_num)
            all_results.append(fr)

    if not all_results:
        return []

    # Sort by Sharpe (highest first)
    sorted_results = sorted(all_results, key=lambda x: x.get("sharpe", 0) or 0, reverse=True)

    # Deduplicate by exact expression match only
    seen_exprs: set[str] = set()
    kept: list[dict] = []
    for fr in sorted_results:
        expr = fr.get("expression", "").strip()
        if expr not in seen_exprs:
            seen_exprs.add(expr)
            kept.append(fr)
        if len(kept) >= n_top:
            break

    return kept[:n_top]


def _collect_all_factors(output_dir: Path) -> list[dict]:
    """Collect all factor results across all iterations for Pareto analysis."""
    bt_all_path = output_dir / "backtest_results_all.json"
    if not bt_all_path.is_file():
        return []

    all_bt = json.loads(bt_all_path.read_text(encoding="utf-8-sig"))
    all_factors: list[dict] = []

    iterations = all_bt.get("iterations", [all_bt])
    for it in iterations:
        for fr in it.get("factor_results", it.get("results", [])):
            if "error" in fr or fr.get("sharpe") is None:
                continue
            all_factors.append(fr)

    # Deduplicate by expression (keep first occurrence)
    seen = set()
    unique = []
    for f in all_factors:
        expr = f.get("expression", "").strip()
        if expr not in seen:
            seen.add(expr)
            unique.append(f)
    return unique


def _cleanup_intermediate_files(output_dir: Path) -> None:
    """Remove intermediate files that should not appear in final output.

    Per the output contract in SKILL.md, these files are intermediate
    and should be cleaned after the run:
    - candidates.json (initial input)
    - validated_factors_passed.json (validation output)
    - next_candidates.json (generation output)
    """
    intermediates = [
        "candidates.json",
        "validated_factors_passed.json",
        "next_candidates.json",
        "transform_prompt.md",
        "llm_response.json",
    ]
    for fname in intermediates:
        fpath = output_dir / fname
        if fpath.is_file():
            fpath.unlink()
            print(f"[INFO] Cleaned intermediate: {fname}", file=sys.stderr)


def _load_active_config() -> dict:
    """Return the full config.json used for this run."""
    cfg_path = Path(__file__).resolve().parent.parent / "config.json"
    if not cfg_path.is_file():
        return {"error": "config.json not found"}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e)}


def _load_query(output_dir: Path) -> str:
    """Load the original user query from candidate_evolution.json if available."""
    evo_path = output_dir / "candidate_evolution.json"
    if evo_path.is_file():
        try:
            evo = json.loads(evo_path.read_text(encoding="utf-8-sig"))
            return evo.get("query", "")
        except Exception:
            pass
    return ""


def _compute_pareto_frontier(
    factors: list[dict],
    objectives: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """Compute the Pareto frontier across multiple objectives.

    Default objectives: maximize Sharpe, minimize turnover, minimize max_drawdown.
    A factor dominates another if it is better in ALL objectives.

    Args:
        factors: List of factor result dicts with sharpe, turnover, max_drawdown, etc.
        objectives: List of (metric_key, direction) tuples.
                    direction is 'maximize' or 'minimize'.

    Returns:
        List of non-dominated (Pareto-optimal) factors.
    """
    if objectives is None:
        objectives = [
            ("sharpe", "maximize"),
            ("turnover", "minimize"),
            ("max_drawdown", "maximize"),  # less negative = better
        ]

    if not factors:
        return []

    def dominates(a: dict, b: dict) -> bool:
        """Returns True if factor a dominates factor b."""
        at_least_one_better = False
        for key, direction in objectives:
            va = a.get(key, 0) or 0
            vb = b.get(key, 0) or 0

            if direction == "maximize":
                if va < vb:
                    return False
                if va > vb:
                    at_least_one_better = True
            else:  # minimize
                if va > vb:
                    return False
                if va < vb:
                    at_least_one_better = True
        return at_least_one_better

    pareto = []
    for i, fi in enumerate(factors):
        dominated = False
        for j, fj in enumerate(factors):
            if i == j:
                continue
            if dominates(fj, fi):
                dominated = True
                break
        if not dominated:
            pareto.append(fi)

    return pareto


def _build_backtest_config_section(output_dir: Path) -> str:
    """Build a markdown section describing the backtest configuration used.

    Reads from config.json in the output directory (copied during summary).
    Falls back to skill-root config.json if output copy is missing.
    """
    cfg_path = output_dir / "config.json"
    if not cfg_path.is_file():
        cfg_path = Path(__file__).resolve().parent.parent / "config.json"
    if not cfg_path.is_file():
        return ""

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    bt = cfg.get("backtest", {})

    indicator = bt.get("indicator", "000300")
    indicator_label = {"000300": "CSI 300", "000905": "CSI 500", "000016": "SZ 50", "399006": "GEM"}.get(indicator, indicator)

    start = bt.get("start_date", "N/A")
    end = bt.get("end_date", "N/A")
    holding = bt.get("holding_days", 5)
    cost = bt.get("cost_bps", 5.0)
    n_quantiles = bt.get("n_quantiles", 5)
    long_pct = bt.get("long_pct", 0.2)
    short_pct = bt.get("short_pct", 0.2)

    # Format dates nicely
    def _fmt_date(d: str) -> str:
        if len(d) == 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return d

    return f"""
## ⚙️ Backtest Configuration

| Parameter | Value |
|-----------|-------|
| **Universe** | {indicator_label} (`{indicator}`) |
| **Period** | {_fmt_date(start)} → {_fmt_date(end)} |
| **Rebalance** | Every {holding} trading day{'s' if holding != 1 else ''} |
| **Positions** | Long top {long_pct*100:.0f}%, short bottom {short_pct*100:.0f}% ({n_quantiles} quantiles) |
| **Cost** | {cost} bps one-way |

"""


def _build_pareto_table(pareto_factors: list[dict]) -> str:
    """Build a markdown table for the Pareto frontier."""
    if not pareto_factors:
        return ""

    # Sort by Sharpe descending for display
    sorted_pareto = sorted(pareto_factors, key=lambda x: x.get("sharpe", 0) or 0, reverse=True)

    rows = []
    for i, f in enumerate(sorted_pareto[:10]):
        sharpe = f.get("sharpe", 0) or 0
        turnover = f.get("turnover", 0) or 0
        max_dd = f.get("max_drawdown", 0) or 0
        annual_ret = f.get("annual_return", 0) or 0
        ic_mean = f.get("ic_mean", 0) or 0
        expr = (f.get("expression", "") or "")[:70]
        rows.append(
            f"| {i+1} | {sharpe:.4f} | {annual_ret:.4f} | {max_dd:.4f} | "
            f"{turnover:.2f} | {ic_mean:.4f} | `{expr}` |"
        )

    return f"""
## 📊 Pareto Frontier (Sharpe vs. Turnover vs. Drawdown)

*Non-dominated factors — each is optimal in at least one trade-off dimension.*

| # | Sharpe | Ann.Ret | MaxDD | Turnover | IC Mean | Expression |
|---|--------|---------|-------|----------|---------|------------|
{chr(10).join(rows)}
"""


def _build_evolution_diagram(
    kb: dict,
    best_factors: list[dict],
    best_history: list[dict],
    output_dir: str = "",
) -> str:
    """Build a Mermaid graph showing how factors evolved across iterations.

    Reads ``candidate_evolution.json`` from the output directory (if it exists)
    for complete parent→child relationships. Falls back to KB best_factor_history
    if no evolution file is found.

    Also saves ``evolution_diagram.md`` to the output directory — open it in
    VS Code with Markdown preview to see the rendered graph.

    Returns a Mermaid ``graph LR`` string.
    """
    import re

    # ── Try candidate_evolution.json first ──────────────────────────────
    evo_path = Path(output_dir) / "candidate_evolution.json" if output_dir else None
    evo_data = None
    if evo_path and evo_path.is_file():
        try:
            evo_data = json.loads(evo_path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass

    lines = ["graph LR"]

    if evo_data and evo_data.get("nodes"):
        # ── Build from evolution file ───────────────────────────────────
        nodes = evo_data["nodes"]
        edges = evo_data.get("edges", [])

        # ── Read backtest results (from accumulated all.json) ──────────
        bt_path = Path(output_dir) / "backtest_results_all.json" if output_dir else None
        bt_by_name: dict[str, dict] = {}
        if bt_path and bt_path.is_file():
            try:
                bt = json.loads(bt_path.read_text(encoding="utf-8-sig"))
                # Extract factor_results from all iterations
                for it in bt.get("iterations", [bt]):
                    for fr in it.get("factor_results", []):
                        if "error" not in fr and fr.get("sharpe") is not None:
                            bt_by_name[fr["name"]] = {
                                "sharpe": fr.get("sharpe", 0),
                                "ic_mean": fr.get("ic_mean"),
                                "turnover": fr.get("turnover"),
                                "annual_return": fr.get("annual_return"),
                                "max_drawdown": fr.get("max_drawdown"),
                            }
            except Exception:
                pass

        # ── Fill metrics from cumulative results ────────────────────────
        for node in nodes:
            nid = node["id"]
            if nid in bt_by_name and bt_by_name[nid]["sharpe"] != 0:
                node["sharpe"] = bt_by_name[nid]["sharpe"]
                node["ic_mean"] = bt_by_name[nid].get("ic_mean")
                node["turnover"] = bt_by_name[nid].get("turnover")
                node["annual_return"] = bt_by_name[nid].get("annual_return")
                node["max_drawdown"] = bt_by_name[nid].get("max_drawdown")

        # Build node lookup
        node_ids: dict[str, str] = {}
        for i, n in enumerate(nodes):
            node_ids[n["id"]] = f"N{i}"

        # Find max Sharpe for star marking (raw value — higher is better)
        sharpes = [n.get("sharpe", 0) or 0 for n in nodes]
        max_sharpe = max(sharpes) if sharpes else 0

        # Add nodes with key metrics + descriptive tags
        for n in nodes:
            nid = node_ids[n["id"]]
            label = n.get("label", n["id"])[:100]
            sharpe = n.get("sharpe", 0) or 0
            ic = n.get("ic_mean")
            turnover = n.get("turnover")
            annual_ret = n.get("annual_return")
            max_dd = n.get("max_drawdown")
            iteration = n.get("iteration", 1)
            is_parent = n.get("is_parent", False)
            star = " ⭐" if sharpe >= max_sharpe and sharpe != 0 else ""
            parent_tag = " 🎯" if is_parent else ""
            display = label + ("…" if len(n.get("label", "")) > 100 else "")

            # Build metrics line
            metric_parts = [f"S {sharpe:.2f}"]
            if ic is not None:
                metric_parts.append(f"IC {ic:.3f}")
            if turnover is not None:
                metric_parts.append(f"TO {turnover:.2f}")
            if annual_ret is not None:
                metric_parts.append(f"AR {annual_ret:.2f}")
            if max_dd is not None:
                metric_parts.append(f"DD {max_dd:.2f}")
            metrics_str = " | ".join(metric_parts)

            # Build descriptive tags — clear English, 🟢/🔴 only
            tags = []
            abs_s = abs(sharpe)
            abs_ic = abs(ic) if ic is not None else 0
            to = turnover or 0
            dd = max_dd or 0
            ar = annual_ret or 0

            # Sharpe — actual value, lower = worse
            if sharpe >= TAG_HIGH_SHARPE:
                tags.append("🟢 high Sharpe")
            elif abs_s < TAG_LOW_SHARPE_ABS:
                tags.append("🔴 low Sharpe")

            # IC — uses abs
            if abs_ic >= TAG_HIGH_IC_ABS:
                tags.append("🟢 high IC")
            elif abs_ic < TAG_LOW_IC_ABS:
                tags.append("🔴 low IC")

            # Turnover
            if to > TAG_HIGH_TURNOVER:
                tags.append("🔴 high turnover")
            elif to < TAG_LOW_TURNOVER:
                tags.append("🟢 low turnover")

            # Drawdown
            if dd < TAG_HIGH_DRAWDOWN:
                tags.append("🔴 high drawdown")

            # Positive return
            if ar > 0:
                tags.append("🟢 positive return")

            tag_str = "  ".join(tags)
            header = f"{star}{parent_tag} " if (star or parent_tag) else ""

            lines.append(
                f'    {nid}["{header}{display}<br/>{metrics_str} (iter {iteration})<br/>{tag_str}"]'
            )

        # Add edges with transformation labels
        for e in edges:
            from_id = node_ids.get(e["from"])
            to_id = node_ids.get(e["to"])
            if from_id and to_id:
                trans = e.get("transformation", "")
                lines.append(f'    {from_id} -->|"{trans}"| {to_id}')

        # If no edges, connect initial factors to their generation
        if not edges:
            initial = [n for n in nodes if n.get("iteration") == 1]
            later = [n for n in nodes if n.get("iteration", 1) > 1]
            for lf in later:
                for inf in initial:
                    if inf["id"] in lf["id"]:
                        lines.append(
                            f'    {node_ids[inf["id"]]} -->|"variant"| {node_ids[lf["id"]]}'
                        )
                        break

    else:
        # ── Fallback: build from KB ─────────────────────────────────────
        factor_info: dict[str, dict] = {}

        for h in best_history:
            name = h.get("factor", "")
            if name:
                # Try to find the exact expression by looking up in backtest results
                expr_display = name  # fallback: use factor name as display
                # Try matching: the factor name is derived from parent + transformation
                # Use the full name as display, truncated for readability
                factor_info[name] = {
                    "sharpe": h.get("sharpe", 0),
                    "iteration": h.get("iteration", 1),
                    "expression": name,
                }

        if len(factor_info) < 2:
            result = "graph LR\n    A[No evolution data — single iteration]"
            if output_dir:
                _write_md(Path(output_dir) / "evolution_diagram.md", result)
            return result

        sorted_factors = sorted(factor_info.items(), key=lambda x: x[1]["iteration"])
        node_ids = {}
        max_sharpe = max((f[1]["sharpe"] for f in sorted_factors), default=0)

        for i, (name, info) in enumerate(sorted_factors):
            node_ids[name] = f"N{i}"
            sharpe = info["sharpe"]
            expr = info.get("expression", "") or name
            star = " ⭐" if sharpe >= max_sharpe else ""
            display = expr[:50] + ("…" if len(expr) > 50 else "")
            lines.append(
                f'    {node_ids[name]}["{display}<br/>Sharpe {sharpe:.2f} (iter {info["iteration"]}){star}"]'
            )

        for name in node_ids:
            variant_match = re.match(r'^(.+?)_v\d+_.+$', name)
            if variant_match:
                potential_parent = variant_match.group(1)
                if potential_parent in node_ids and node_ids[potential_parent] != node_ids[name]:
                    trans_match = re.search(r'_v\d+_(.+)$', name)
                    trans = trans_match.group(1) if trans_match else "variant"
                    lines.append(
                        f'    {node_ids[potential_parent]} -->|"{trans}"| {node_ids[name]}'
                    )

    result = "\n".join(lines)

    # ── Save .md file for visual rendering ──────────────────────────────
    if output_dir:
        query = _load_query(Path(output_dir)) if output_dir else ""
        _write_md(Path(output_dir) / "evolution_diagram.md", result, output_dir, query)

    return result


def _build_transform_reference(output_dir: Path) -> str:
    """Build a transformation reference table showing only transforms used in this run.

    Reads ``candidate_evolution.json`` to find which transformation labels
    appear on edges, and ``transform_suggestions.json`` for LLM-provided
    rationales. Built-in transforms use the rationale map from contracts.
    """
    from contracts import TRANSFORMATION_RATIONALE_MAP

    evo_path = output_dir / "candidate_evolution.json"
    if not evo_path.is_file():
        return _static_transform_ref()

    try:
        evo = json.loads(evo_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return _static_transform_ref()

    edges = evo.get("edges", [])
    if not edges:
        return _static_transform_ref()

    # ── Load LLM rationales from transform_suggestions.json ────────────
    llm_rationales: dict[str, str] = {}
    suggestions_path = output_dir / "transform_suggestions.json"
    if suggestions_path.is_file():
        try:
            payload = json.loads(suggestions_path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, list):
                suggestions = payload
            elif isinstance(payload, dict):
                suggestions = payload.get("latest_suggestions", [])
                if not suggestions:
                    history = payload.get("suggestion_history", [])
                    for entry in reversed(history):
                        suggestions = entry.get("suggestions", []) if isinstance(entry, dict) else []
                        if suggestions:
                            break
            else:
                suggestions = []
            for s in suggestions:
                trans_name = s.get("transformation", "")
                rationale = s.get("rationale", "")
                if trans_name and rationale:
                    llm_rationales[trans_name] = rationale
        except Exception:
            pass

    # Collect unique transformation labels from edges
    used_transforms: dict[str, str] = {}
    for e in edges:
        trans = e.get("transformation", "")
        if trans and trans not in used_transforms:
            # Prefer LLM rationale, then edge rationale, then built-in map
            if trans in llm_rationales:
                used_transforms[trans] = llm_rationales[trans]
            elif e.get("rationale"):
                used_transforms[trans] = e["rationale"]
            else:
                used_transforms[trans] = TRANSFORMATION_RATIONALE_MAP.get(
                    trans, ""
                )

    if not used_transforms:
        return _static_transform_ref()

    rows = []
    for trans in sorted(used_transforms.keys()):
        rationale = used_transforms[trans]
        rows.append(f"| `{trans}` | {rationale} |")

    return f"""
### Transformation Reference ({len(used_transforms)} used)

| Transformation | Rationale |
|---------------|-----------|
{chr(10).join(rows)}
"""


def _static_transform_ref() -> str:
    """Fallback: full static transformation reference."""
    return """
### Transformation Reference

| Transformation | Rationale |
|---------------|-----------|
| `flip-sign` | Negative Sharpe — inverting recovers a positive Sharpe from a directionally-wrong factor |
| `reduce-turnover` | Turnover exceeds 0.8 — smoothing reduces excessive trading and transaction costs |
| `adjust-lookback` | IC signal is too noisy or too smooth — changing lookback can improve stability |
| `adjust-smoothing` | Turnover is extreme — adjusting smoothing balances signal decay vs. trading cost |
| `adjust-clipping` | Extreme outliers are distorting the signal — clipping caps their influence |
| `adjust-normalization` | Factor distribution is skewed — switching normalization improves comparability |
| `combine-factors` | Both factors are promising with low correlation — combining diversifies alpha |
| `simplify` | Expression is over-complex — removing nesting reduces overfit risk |
| `long-only` | The short leg is underperforming — keeping only longs eliminates dead weight |
| `short-only` | The long leg is underperforming — keeping only shorts eliminates dead weight |
| `asymmetric` | Long and short returns are asymmetric — weighting captures the stronger side |
"""


def _write_md(path: Path, mermaid: str, output_dir: str = "", query: str = "") -> None:
    """Write a Mermaid diagram as a Markdown file for VS Code preview.

    Includes a top-10 factors table, backtest configuration, and
    a transformation reference showing only transforms used in this run.
    """
    # ── Build backtest config section ──────────────────────────────────
    config_section = _build_backtest_config_section(Path(output_dir)) if output_dir else ""

    # ── Build top-10 table ─────────────────────────────────────────────
    top_table = ""
    if output_dir:
        filtered = _compute_filtered_top_factors(Path(output_dir), n_top=10)
        if filtered:
            rows = []
            for i, f in enumerate(filtered):
                sharpe_val = f.get("sharpe", 0) or 0
                expr = (f.get("expression", "") or "")[:80]
                iteration = f.get("_iteration", "-")
                rows.append(
                    f"| {i+1} | {sharpe_val:.4f} | {f.get('annual_return', 0) or 0:.4f} | "
                    f"{f.get('max_drawdown', 0) or 0:.4f} | {f.get('turnover', 0) or 0:.2f} | "
                    f"{f.get('ic_mean', 0) or 0:.4f} | {f.get('icir', 0) or 0:.4f} | "
                    f"{iteration} | `{expr}` |"
                )
            top_table = f"""
## 🏆 Top 10 Factors (Ranked by Sharpe)

| # | Sharpe | Ann.Ret | MaxDD | Turnover | IC Mean | ICIR | Iter | Expression |
|---|--------|---------|-------|----------|---------|------|------|------------|
{chr(10).join(rows)}
"""

    # ── Build transformation reference (only used transforms) ────────
    transform_ref = _build_transform_reference(Path(output_dir)) if output_dir else _static_transform_ref()

    query_section = ""
    if query:
        query_section = f"""
## 📝 Original User Query

> {query}

"""

    md = f"""# Factor Evolution Diagram

> Open this file in VS Code with Markdown preview (`Cmd+Shift+V`) to see the rendered graph.
{query_section}{config_section}{top_table}
```mermaid
{mermaid}
```

## Metrics Legend

| Abbr | Metric | Meaning |
|------|--------|---------|
| **S** | Sharpe | Risk-adjusted return (sign = direction; negative = short signal) |
| **IC** | IC Mean | Cross-sectional rank correlation with forward returns |
| **TO** | Turnover | Fraction of positions changed between rebalance periods |
| **AR** | Annual Return | Annualized long-short portfolio return |
| **DD** | Max Drawdown | Maximum peak-to-trough decline |

## How to Read This Diagram

- **Nodes** show factor expressions, key metrics, and descriptive tags
- **⭐** marks the factor with the highest numeric Sharpe
- **🎯** marks factors **selected as parents** for the next generation
- **Arrows** show parent → child relationships with the **transformation** applied

### Tag Reference

| Color | Meaning |
|-------|---------|
| 🟢 | Good attribute |
| 🔴 | Warning / poor attribute |

**Tags:** `high Sharpe` (S≥0.5) · `low Sharpe` (S<0.2) · `high IC` (|IC|≥0.02) · `low IC` (|IC|<0.01) · `high turnover` (TO>0.85) · `low turnover` (TO<0.5) · `high drawdown` (DD<−50%) · `positive return` (AR>0)

{transform_ref}
"""
    path.write_text(md, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optimization loop coordinator for factor-loop-evolve."
    )
    parser.add_argument("--summary", action="store_true",
                        help="Generate final optimization summary.")
    parser.add_argument("--check-stall", action="store_true",
                        help="Check stopping criteria.")
    parser.add_argument("--knowledge", type=str, default="knowledge_base.json",
                        help="Path to knowledge base JSON.")
    parser.add_argument("--diagnosis", type=str, default="",
                        help="Path to current diagnosis JSON (for --check-stall).")
    parser.add_argument("--output", type=str, default="",
                        help="Output path for summary (default: output/<run-id>/final_summary.json).")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Run identifier. Auto-generated timestamp if not given.")
    parser.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS,
                        help=f"Max iterations for stall check (default from config: {MAX_ITERATIONS}).")
    parser.add_argument("--min-iterations", type=int, default=MIN_ITERATIONS,
                        help=f"Min iterations before early stop allowed (default from config: {MIN_ITERATIONS}).")
    parser.add_argument("--worth-keeping-sharpe", type=float, default=WORTH_KEEPING_SHARPE_THRESHOLD,
                        help=f"Min Sharpe to mark worth_keeping (default from config: {WORTH_KEEPING_SHARPE_THRESHOLD}).")
    args = parser.parse_args()

    if args.summary:
        out = args.output if args.output else str(_resolve_output("final_summary.json"))
        result = generate_summary(args.knowledge, out)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.check_stall:
        if not args.diagnosis:
            print(json.dumps({"error": "--diagnosis required for --check-stall"}, ensure_ascii=False))
            sys.exit(1)

        kb_path = Path(args.knowledge)
        diag_path = Path(args.diagnosis)

        if not kb_path.is_file():
            print(json.dumps({"error": f"Knowledge base not found: {args.knowledge}"}, ensure_ascii=False))
            sys.exit(1)
        if not diag_path.is_file():
            print(json.dumps({"error": f"Diagnosis not found: {args.diagnosis}"}, ensure_ascii=False))
            sys.exit(1)

        kb = json.loads(kb_path.read_text(encoding="utf-8-sig"))
        diag = json.loads(diag_path.read_text(encoding="utf-8-sig"))

        result = check_stopping_criteria(diag, kb, max_iterations=args.max_iterations)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
