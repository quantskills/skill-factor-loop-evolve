#!/usr/bin/env python3
"""Optimization loop coordinator for skill-factor-optimize.

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

    summary = {
        "iterations": iterations,
        "optimization_log": optimization_log,
        "best_factors": best_factors,
        "worth_keeping": worth_keeping,
        "worth_keeping_rationale": rationale,
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


def _dedup_correlated_nodes(
    nodes: list[dict],
    edges: list[dict],
    bt_by_name: dict[str, dict],
    output_dir: str = "",
    corr_threshold: float = 0.85,
) -> tuple[list[dict], list[dict]]:
    """Remove highly correlated nodes, keeping only the highest Sharpe per cluster.

    Reads IC series from trading_data/ic_series.csv for correlation.
    Redirects edges from removed nodes to the kept node.
    """
    import numpy as np

    n = len(nodes)
    if n <= 1:
        return nodes, edges

    # ── Load IC series from CSV ────────────────────────────────────────
    ic_series_by_name: dict[str, list[float]] = {}
    if output_dir:
        csv_path = Path(output_dir) / "trading_data" / "ic_series.csv"
        if csv_path.is_file():
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)
                for name, grp in df.groupby("factor"):
                    ic_list = grp["ic"].dropna().tolist()
                    if len(ic_list) >= 5:
                        ic_series_by_name[name] = ic_list
            except Exception:
                pass

    # Build correlation matrix
    removed: set[str] = set()
    kept_to_removed: dict[str, list[str]] = {}

    for i in range(n):
        if nodes[i]["id"] in removed:
            continue
        for j in range(i + 1, n):
            if nodes[j]["id"] in removed:
                continue
            ni, nj = nodes[i], nodes[j]
            id_i, id_j = ni["id"], nj["id"]

            ic_i = ic_series_by_name.get(id_i, [])
            ic_j = ic_series_by_name.get(id_j, [])

            is_correlated = False
            if ic_i and ic_j and len(ic_i) >= 5 and len(ic_j) >= 5:
                try:
                    min_len = min(len(ic_i), len(ic_j))
                    corr = np.corrcoef(ic_i[:min_len], ic_j[:min_len])[0, 1]
                    if not np.isnan(corr) and abs(corr) > corr_threshold:
                        is_correlated = True
                except Exception:
                    pass

            # Fallback: expression similarity for nodes without IC data
            if not is_correlated and (not ic_i or not ic_j):
                e1 = ni.get("expression", ni.get("label", ""))
                e2 = nj.get("expression", nj.get("label", ""))
                if e1 and e2:
                    # Normalize: strip whitespace, extract core formula parts
                    def _core(expr: str) -> str:
                        """Extract core formula: the first function chain before any clip/rank wrap."""
                        s = expr.strip().replace(" ", "")
                        # Remove outer clip/rank/decay_linear wrappers for comparison
                        for fn in ["clip(", "rank(", "decay_linear(", "zscore("]:
                            if s.startswith(fn):
                                depth = 0
                                end = len(s)
                                for k, ch in enumerate(s):
                                    if ch == "(": depth += 1
                                    elif ch == ")":
                                        depth -= 1
                                        if depth == 0:
                                            end = k + 1
                                            break
                                inner = s[len(fn):end-1]
                                # Check if there's a comma (multi-arg), take first arg
                                arg_depth = 0
                                for m, ch in enumerate(inner):
                                    if ch == "(": arg_depth += 1
                                    elif ch == ")": arg_depth -= 1
                                    elif ch == "," and arg_depth == 0:
                                        inner = inner[:m]
                                        break
                                return _core(inner)
                        return s
                    c1 = _core(e1)
                    c2 = _core(e2)
                    # Also compare full normalized expressions
                    n1 = e1.strip().replace(" ", "")
                    n2 = e2.strip().replace(" ", "")
                    # Core match OR high token overlap
                    if c1 == c2:
                        is_correlated = True
                    elif len(n1) > 10 and len(n2) > 10:
                        tokens1 = set(n1.replace("(", " ").replace(")", " ").replace(",", " ").replace("/", " ").split())
                        tokens2 = set(n2.replace("(", " ").replace(")", " ").replace(",", " ").replace("/", " ").split())
                        if tokens1 and tokens2:
                            shared = tokens1 & tokens2
                            union = tokens1 | tokens2
                            if len(shared) / len(union) > 0.80:
                                is_correlated = True

            if is_correlated:
                si = ni.get("sharpe", 0) or 0
                sj = nj.get("sharpe", 0) or 0
                if si >= sj:
                    removed.add(id_j)
                    kept_to_removed.setdefault(id_i, []).append(id_j)
                else:
                    removed.add(id_i)
                    kept_to_removed.setdefault(id_j, []).append(id_i)
                    break

    if not removed:
        return nodes, edges

    # Filter nodes
    kept_nodes = [n for n in nodes if n["id"] not in removed]

    # Remap edges: redirect edges to/from removed nodes to their kept node
    removed_to_keeper: dict[str, str] = {}
    for keeper, rem_list in kept_to_removed.items():
        for r in rem_list:
            removed_to_keeper[r] = keeper

    new_edges = []
    seen_edge_keys = set()
    for e in edges:
        frm = e["from"]
        to = e["to"]

        # Redirect if either endpoint was removed
        if frm in removed_to_keeper:
            frm = removed_to_keeper[frm]
        if to in removed_to_keeper:
            to = removed_to_keeper[to]

        # Skip self-loops
        if frm == to:
            continue

        # Deduplicate edges
        key = (frm, to, e.get("transformation", ""))
        if key not in seen_edge_keys:
            seen_edge_keys.add(key)
            new_edges.append({**e, "from": frm, "to": to})

    return kept_nodes, new_edges


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
            if sharpe >= 0.5:
                tags.append("🟢 high Sharpe")
            elif sharpe < 0.2:
                tags.append("🔴 low Sharpe")

            # IC — uses abs
            if abs_ic >= 0.02:
                tags.append("🟢 high IC")
            elif abs_ic < 0.01:
                tags.append("🔴 low IC")

            # Turnover
            if to > 0.85:
                tags.append("🔴 high turnover")
            elif to < 0.5:
                tags.append("🟢 low turnover")

            # Drawdown
            if dd < -0.5:
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
                trans = e.get("transformation", "")[:20]
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
        # Build from best_factor_history with full factor names
        # Look up full expressions from successful_patterns by exact match
        pattern_by_expr = {}
        for sp in kb.get("successful_patterns", []):
            pat = sp.get("pattern", "")
            if pat:
                pattern_by_expr[pat] = sp

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
                        f'    {node_ids[potential_parent]} -->|"{trans[:20]}"| {node_ids[name]}'
                    )

    result = "\n".join(lines)

    # ── Save .md file for visual rendering ──────────────────────────────
    if output_dir:
        _write_md(Path(output_dir) / "evolution_diagram.md", result, output_dir)

    return result


def _write_md(path: Path, mermaid: str, output_dir: str = "") -> None:
    """Write a Mermaid diagram as a Markdown file for VS Code preview.

    Includes a top-10 factors table ranked by Sharpe.
    """
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

    md = f"""# Factor Evolution Diagram

> Open this file in VS Code with Markdown preview (`Cmd+Shift+V`) to see the rendered graph.
{top_table}
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

### Transformation Reference

| Transformation | Effect | Trigger |
|---------------|--------|---------|
| `reduce-turnover` | Smooth with 20-day moving average | high turnover |
| `adjust-smoothing` | Add or remove decay-linear weighting | turnover too high or low |
| `adjust-lookback` | Adjust rolling window length by ±50% | IC too noisy or too smooth |
| `adjust-normalization` | Switch between rank, z-score, or scale | distribution skew |
| `adjust-clipping` | Clip values to bounded range | extreme outlier spikes |
| `flip-sign` | Negate the entire expression | negative Sharpe |
| `asymmetric` | Weight long side more than short side | asymmetric return profile |
| `long-only` | Keep only positive values (clip at zero) | short side underperforming |
| `short-only` | Keep only negative values (clip at zero) | long side underperforming |
| `combine-factors` | Add two z-scored factors together | two promising low-correlation factors |
| `simplify` | Remove one level of nesting | over-complex expression |
"""
    path.write_text(md, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optimization loop coordinator for factor-optimize."
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
