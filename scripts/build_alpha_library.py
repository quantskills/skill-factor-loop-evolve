#!/usr/bin/env python3
"""Consolidate all run final_summary.json files into a unified alpha library.

Scans ``output/run_*/final_summary.json``, extracts the best factors from
each run, deduplicates by expression (keeping the best Sharpe), and outputs
a sorted alpha library JSON.

Usage::

    python scripts/build_alpha_library.py
    python scripts/build_alpha_library.py --min-sharpe 0.0
    python scripts/build_alpha_library.py --output alpha_library.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"


def _safe_name(expr: str) -> str:
    """Derive a short slug from a factor expression."""
    expr = expr.strip()
    # Replace common patterns with readable names
    name = expr.lower()
    name = re.sub(r"[^0-9a-z_]+", "_", name)
    name = name.strip("_")
    # Truncate to reasonable length
    return name[:60] if len(name) > 60 else name


def load_run(run_dir: Path) -> dict | None:
    """Load a single run's final_summary.json and return structured data."""
    summary_path = run_dir / "final_summary.json"
    if not summary_path.exists():
        return None

    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠ Skipping {run_dir.name}: {e}", file=sys.stderr)
        return None

    best_factors = data.get("best_factors", [])
    if not best_factors:
        return None

    query = data.get("query", "")
    worth_keeping = data.get("worth_keeping", False)

    return {
        "run": run_dir.name,
        "query": query,
        "worth_keeping": worth_keeping,
        "best_factors": best_factors,
    }


def build_library(
    output_dir: Path,
    min_sharpe: float | None = None,
) -> dict:
    """Build the consolidated alpha library.

    Args:
        output_dir: Path to the output/ directory containing run_* folders.
        min_sharpe: If set, only include factors with Sharpe ≥ this threshold.

    Returns:
        Dict with ``entries`` (list of factor dicts) and ``meta``.
    """
    run_dirs = sorted(
        [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("run_")],
        reverse=True,  # newest first
    )

    if not run_dirs:
        print("No run_* directories found.", file=sys.stderr)
        return {"entries": [], "meta": {}}

    print(f"Found {len(run_dirs)} run directories", file=sys.stderr)

    # Collect all factors keyed by expression → best (sharpe, run, query)
    all_factors: dict[str, dict] = {}

    for run_dir in run_dirs:
        run_data = load_run(run_dir)
        if run_data is None:
            continue

        print(
            f"  {run_dir.name}: {len(run_data['best_factors'])} best factors "
            f"(worth_keeping={run_data['worth_keeping']})",
            file=sys.stderr,
        )

        for bf in run_data["best_factors"]:
            expr = bf.get("factor", "").strip()
            sharpe = bf.get("sharpe")
            if not expr or sharpe is None:
                continue

            # Normalize whitespace in expression for dedup key
            key = " ".join(expr.split())

            if min_sharpe is not None and sharpe < min_sharpe:
                continue

            if key not in all_factors or sharpe > all_factors[key]["sharpe"]:
                all_factors[key] = {
                    "expression": expr,
                    "sharpe": round(sharpe, 4),
                    "source_run": run_dir.name,
                    "source_query": run_data["query"] or "",
                    "worth_keeping": run_data["worth_keeping"],
                    "slug": _safe_name(expr),
                }

    # Sort by Sharpe descending
    entries = sorted(all_factors.values(), key=lambda f: f["sharpe"], reverse=True)

    # Compute stats
    sharpes = [e["sharpe"] for e in entries]
    positive = sum(1 for s in sharpes if s > 0)
    n_runs = len({e["source_run"] for e in entries})

    print(
        f"\nTotal unique factors: {len(entries)} from {n_runs} runs "
        f"({positive} positive Sharpe)",
        file=sys.stderr,
    )

    return {
        "meta": {
            "total_factors": len(entries),
            "total_runs_scanned": len(run_dirs),
            "total_runs_contributing": n_runs,
            "positive_sharpe_count": positive,
            "best_sharpe": round(max(sharpes), 4) if sharpes else None,
            "worst_sharpe": round(min(sharpes), 4) if sharpes else None,
            "min_sharpe_filter": min_sharpe,
            "generated_from": str(output_dir),
        },
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build alpha library from factor-loop-evolve runs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "alpha_library.json",
        help="Output JSON path (default: alpha_library.json at skill root)",
    )
    parser.add_argument(
        "--min-sharpe",
        type=float,
        default=None,
        help="Only include factors with Sharpe >= this value",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory containing run_* folders",
    )
    args = parser.parse_args()

    if not args.output_dir.is_dir():
        print(f"Error: output directory not found: {args.output_dir}", file=sys.stderr)
        sys.exit(1)

    library = build_library(args.output_dir, min_sharpe=args.min_sharpe)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(library, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nAlpha library written to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
