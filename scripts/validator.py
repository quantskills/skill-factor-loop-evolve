#!/usr/bin/env python3
"""Factor expression validator for skill-factor-optimize.

Validates alpha factor expressions against the field/function contract,
checks for look-ahead bias, numerical stability, and complexity limits.
Uses synthetic toy data for computability checks.

Usage::

    python scripts/validator.py --factors candidates.json
    python scripts/validator.py --factors candidates.json --correction-context
    python scripts/validator.py --factors candidates.json --output validated.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy")

# Allow importing from scripts directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import (  # noqa: E402
    ALLOWED_FIELDS,
    ALLOWED_FUNCTIONS,
    ANTI_BIAS_RULES,
    STABILITY_RULES,
    MAX_EXPRESSION_LENGTH,
    MAX_NESTING_DEPTH,
    MAX_FUNCTION_CALLS,
    MIN_ROLLING_N,
    MAX_ROLLING_N,
    build_correction_prompt,
    output_path as _resolve_output,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Toy Data Generator
# ═══════════════════════════════════════════════════════════════════════════════

def make_toy_data(
    num_dates: int = 252,
    num_symbols: int = 5,
    seed: int = 42,
) -> pd.DataFrame:
    """Create synthetic OHLCV data for factor validation."""
    rng = np.random.default_rng(seed)
    symbols = [f"TEST{i:03d}" for i in range(num_symbols)]
    dates = pd.date_range("2024-01-01", periods=num_dates, freq="B")

    rows: list[dict[str, Any]] = []
    for sym in symbols:
        drift = rng.normal(0.0002, 0.0005)
        base_price = rng.uniform(10, 100)
        close_prices: list[float] = []
        for _ in range(num_dates):
            ret = rng.normal(drift, 0.02)
            base_price *= (1 + ret)
            close_prices.append(base_price)

        for d_idx, date in enumerate(dates):
            c = close_prices[d_idx]
            daily_range = c * rng.uniform(0.01, 0.04)
            o = c * rng.uniform(0.98, 1.02)
            h = max(o, c) + daily_range * rng.uniform(0, 0.5)
            l = min(o, c) - daily_range * rng.uniform(0, 0.5)
            v = rng.integers(100_000, 10_000_000)
            rows.append({
                "date": date.strftime("%Y%m%d"),
                "symbol": sym,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": float(v),
                "amount": round(c * v, 2),
            })

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════════
# Toy Factor Engine
# ═══════════════════════════════════════════════════════════════════════════════

class ToyFactorEngine:
    """Lightweight engine for evaluating factor expressions on toy data."""

    def __init__(self, data: pd.DataFrame):
        self._raw = data.copy()
        self._pivoted: dict[str, pd.DataFrame] = {}
        for col in ALLOWED_FIELDS:
            pivot = data.pivot_table(
                index="date", columns="symbol", values=col, aggfunc="first"
            )
            pivot.index = pd.to_datetime(pivot.index, format="%Y%m%d")
            pivot = pivot.sort_index()
            self._pivoted[col] = pivot

    def _get_field(self, name: str) -> pd.DataFrame:
        return self._pivoted[name]

    def evaluate(self, expression: str) -> pd.DataFrame | None:
        """Evaluate a factor expression. Returns DataFrame or None on error."""
        try:
            local_vars = {
                field: self._get_field(field)
                for field in ALLOWED_FIELDS
            }
            local_vars.update({
                "rank": self._rank,
                "zscore": self._zscore,
                "scale": self._scale,
                "ts_rank": self._ts_rank,
                "ts_zscore": self._ts_zscore,
                "ts_mean": self._ts_mean,
                "ts_std": self._ts_std,
                "ts_max": self._ts_max,
                "ts_min": self._ts_min,
                "ts_sum": self._ts_sum,
                "ts_argmax": self._ts_argmax,
                "ts_argmin": self._ts_argmin,
                "correlation": self._correlation,
                "covariance": self._covariance,
                "decay_linear": self._decay_linear,
                "delay": self._delay,
                "delta": self._delta,
                "returns": self._returns,
                "adv": self._adv,
                "sign": np.sign,
                "log": np.log,
                "abs": np.abs,
                "power": self._power,
                "signed_power": self._signed_power,
                "min": np.minimum,
                "max": np.maximum,
                "clip": np.clip,
            })
            result = eval(expression, {"__builtins__": {}}, local_vars)
            if isinstance(result, pd.DataFrame):
                return result
            return pd.DataFrame(result)
        except Exception:
            return None

    # ── Cross-sectional functions ────────────────────────────────────────

    @staticmethod
    def _rank(x: pd.DataFrame) -> pd.DataFrame:
        return x.rank(axis=1, pct=True)

    @staticmethod
    def _zscore(x: pd.DataFrame) -> pd.DataFrame:
        return x.subtract(x.mean(axis=1), axis=0).div(
            x.std(axis=1).replace(0, 1e-8), axis=0
        )

    @staticmethod
    def _scale(x: pd.DataFrame, a: float = 1.0) -> pd.DataFrame:
        return x.div(x.abs().sum(axis=1).replace(0, 1e-8), axis=0) * a

    # ── Rolling functions ────────────────────────────────────────────────

    @staticmethod
    def _ts_rank(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).apply(
            lambda s: s.rank(pct=True).iloc[-1], raw=False
        )

    @staticmethod
    def _ts_zscore(x: pd.DataFrame, n: int) -> pd.DataFrame:
        roll_mean = x.rolling(n, min_periods=max(1, n // 2)).mean()
        roll_std = x.rolling(n, min_periods=max(1, n // 2)).std().replace(0, 1e-8)
        return (x - roll_mean) / roll_std

    @staticmethod
    def _ts_mean(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).mean()

    @staticmethod
    def _ts_std(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).std()

    @staticmethod
    def _ts_max(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).max()

    @staticmethod
    def _ts_min(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).min()

    @staticmethod
    def _ts_sum(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).sum()

    @staticmethod
    def _ts_argmax(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).apply(
            lambda s: n - 1 - s.values.argmax() if len(s) > 0 else 0, raw=False
        )

    @staticmethod
    def _ts_argmin(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).apply(
            lambda s: n - 1 - s.values.argmin() if len(s) > 0 else 0, raw=False
        )

    @staticmethod
    def _correlation(x: pd.DataFrame, y: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).corr(y)

    @staticmethod
    def _covariance(x: pd.DataFrame, y: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.rolling(n, min_periods=max(1, n // 2)).cov(y)

    @staticmethod
    def _decay_linear(x: pd.DataFrame, n: int) -> pd.DataFrame:
        weights = np.arange(1, n + 1) / np.arange(1, n + 1).sum()

        def _wavg(s):
            if len(s) < len(weights):
                w = weights[-len(s):]
                w = w / w.sum()
                return np.average(s, weights=w)
            return np.average(s, weights=weights)

        return x.rolling(n, min_periods=max(1, n // 2)).apply(_wavg, raw=True)

    # ── Lag / difference / returns ───────────────────────────────────────

    @staticmethod
    def _delay(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.shift(n)

    @staticmethod
    def _delta(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x - x.shift(n)

    @staticmethod
    def _returns(x: pd.DataFrame, n: int = 1) -> pd.DataFrame:
        return x.pct_change(n)

    def _adv(self, n: int) -> pd.DataFrame:
        return self._pivoted["volume"].rolling(
            n, min_periods=max(1, n // 2)
        ).mean()

    # ── Element-wise math ────────────────────────────────────────────────

    @staticmethod
    def _power(x: pd.DataFrame, n: float) -> pd.DataFrame:
        return x ** n

    @staticmethod
    def _signed_power(x: pd.DataFrame, n: float) -> pd.DataFrame:
        return np.sign(x) * (np.abs(x) ** n)


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Logic
# ═══════════════════════════════════════════════════════════════════════════════

def _check_syntax(expression: str) -> str | None:
    """Check Python syntax. Returns error message or None."""
    try:
        ast.parse(expression)
        return None
    except SyntaxError as e:
        return f"Syntax error: {e}"


def _check_fields(expression: str) -> list[str]:
    """Check for unsupported field references. Returns list of violations."""
    violations = []
    # Extract identifiers that look like field references
    tokens = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', expression)
    builtin_like = {"True", "False", "None", "and", "or", "not", "if", "else", "for", "while"}
    for token in tokens:
        if token in builtin_like:
            continue
        if token in ALLOWED_FUNCTIONS:
            continue
        if token in ALLOWED_FIELDS:
            continue
        # Check if it's a number
        try:
            float(token)
            continue
        except ValueError:
            pass
        # Check if it looks like a field but isn't
        if token.lower() in {"vwap", "adjfactor", "turnover", "market_cap", "float_mv",
                              "pe", "pb", "roe", "roa", "eps", "bps", "dividend",
                              "shares", "mktcap", "cap"}:
            violations.append(f"Unsupported field: '{token}'")
    return violations


def _check_lookahead(expression: str) -> list[str]:
    """Check for look-ahead bias. Returns list of violations."""
    violations = []
    # delay(x, 0) or delay(x, -1)
    delay_matches = re.findall(r'delay\s*\([^,]+,\s*(-?\d+)', expression)
    for n_str in delay_matches:
        n = int(n_str)
        if n <= 0:
            violations.append(
                f"Look-ahead bias: delay(..., {n}) uses n <= 0"
            )

    # delta(x, 0) or delta(x, -1)
    delta_matches = re.findall(r'delta\s*\([^,]+,\s*(-?\d+)', expression)
    for n_str in delta_matches:
        n = int(n_str)
        if n <= 0:
            violations.append(
                f"Look-ahead bias: delta(..., {n}) uses n <= 0"
            )

    # returns(x, 0) or returns(x, -1) — note returns can have 1 or 2 args
    returns_matches = re.findall(r'returns\s*\([^)]+\)', expression)
    for match in returns_matches:
        args = match[match.index('(') + 1:match.rindex(')')]
        parts = [p.strip() for p in args.split(',')]
        if len(parts) >= 2:
            try:
                n = int(parts[1])
                if n <= 0:
                    violations.append(
                        f"Look-ahead bias: returns(..., {n}) uses n <= 0"
                    )
            except ValueError:
                pass

    return violations


def _check_complexity(expression: str) -> list[str]:
    """Check complexity limits. Returns list of warnings."""
    warnings_list = []

    # Length check
    if len(expression) > MAX_EXPRESSION_LENGTH:
        warnings_list.append(
            f"Complexity: expression length {len(expression)} > {MAX_EXPRESSION_LENGTH}"
        )

    # Nesting depth (count parentheses)
    depth = 0
    max_depth = 0
    for ch in expression:
        if ch == '(':
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == ')':
            depth -= 1
    if max_depth > MAX_NESTING_DEPTH:
        warnings_list.append(
            f"Complexity: nesting depth {max_depth} > {MAX_NESTING_DEPTH}"
        )

    # Function call count
    func_calls = len(re.findall(
        r'\b(rank|zscore|scale|ts_rank|ts_zscore|ts_mean|ts_std|ts_max|ts_min|'
        r'ts_sum|ts_argmax|ts_argmin|correlation|covariance|decay_linear|'
        r'delay|delta|returns|adv|sign|log|abs|power|signed_power|min|max|clip)\s*\(',
        expression,
    ))
    if func_calls > MAX_FUNCTION_CALLS:
        warnings_list.append(
            f"Complexity: {func_calls} function calls > {MAX_FUNCTION_CALLS}"
        )

    return warnings_list


def _check_rolling_params(expression: str) -> list[str]:
    """Check rolling window parameters are within bounds. Returns warnings."""
    warnings_list = []
    rolling_funcs = [
        'ts_rank', 'ts_zscore', 'ts_mean', 'ts_std', 'ts_max', 'ts_min',
        'ts_sum', 'ts_argmax', 'ts_argmin', 'correlation', 'covariance',
        'decay_linear', 'delay', 'delta', 'returns', 'adv',
    ]

    for func in rolling_funcs:
        # Use paren-aware matching for nested function calls
        for match in re.finditer(rf'{func}\s*\(', expression):
            start = match.end()
            depth = 1
            i = start
            while i < len(expression) and depth > 0:
                if expression[i] == '(':
                    depth += 1
                elif expression[i] == ')':
                    depth -= 1
                i += 1
            args_str = expression[start:i-1]
            # Split only on commas at depth 0
            args = []
            d = 0
            current = []
            for ch in args_str:
                if ch == '(':
                    d += 1
                    current.append(ch)
                elif ch == ')':
                    d -= 1
                    current.append(ch)
                elif ch == ',' and d == 0:
                    args.append(''.join(current).strip())
                    current = []
                else:
                    current.append(ch)
            if current:
                args.append(''.join(current).strip())
            for arg in args:
                try:
                    val = int(arg)
                    if val < MIN_ROLLING_N and func not in ('returns',):
                        warnings_list.append(
                            f"Small window: {func}(..., {val}) — n < {MIN_ROLLING_N}"
                        )
                    if val > MAX_ROLLING_N:
                        warnings_list.append(
                            f"Large window: {func}(..., {val}) — n > {MAX_ROLLING_N}"
                        )
                except ValueError:
                    pass
    return warnings_list


def _check_numerical_computability(
    engine: ToyFactorEngine, expression: str
) -> tuple[bool, str | None]:
    """Check if expression can be computed on toy data without NaN/Inf issues."""
    result = engine.evaluate(expression)
    if result is None:
        return False, "Evaluation failed (syntax or runtime error)"

    if not isinstance(result, pd.DataFrame):
        return False, f"Result is not a DataFrame (got {type(result).__name__})"

    values = result.values
    flat = values[~np.isnan(values)]

    if len(flat) == 0:
        return False, "All values are NaN"

    nan_ratio = np.isnan(values).mean()
    inf_ratio = np.isinf(values).mean()

    if nan_ratio > 0.5:
        return False, f"NaN ratio {nan_ratio:.1%} > 50%"

    if inf_ratio > 0.1:
        return False, f"Inf ratio {inf_ratio:.1%} > 10%"

    # Check for extreme values
    abs_vals = np.abs(flat)
    extreme_ratio = np.mean(abs_vals > 1e6)
    if extreme_ratio > 0.1:
        return False, f"Extreme values: {extreme_ratio:.1%} have |value| > 1e6"

    return True, None


def validate_factors(factors: list[dict]) -> dict:
    """Validate a list of factor candidates.

    Args:
        factors: List of factor dicts with name, expression, etc.

    Returns:
        Dict with total, passed, failed, results, correction_context.
    """
    toy_data = make_toy_data()
    engine = ToyFactorEngine(toy_data)

    results = []
    passed_count = 0
    failed_count = 0

    for factor in factors:
        name = factor.get("name", "unnamed")
        expression = factor.get("expression", "")
        errors = []
        warnings_list = []

        # Required fields check
        if not name or not expression:
            errors.append("Missing required field: name or expression")
            results.append({
                "name": name,
                "expression": expression,
                "ok": False,
                "errors": errors,
                "warnings": warnings_list,
                "eval_time_ms": 0,
            })
            failed_count += 1
            continue

        # 1. Syntax check
        syntax_err = _check_syntax(expression)
        if syntax_err:
            errors.append(syntax_err)

        # 2. Field check
        field_violations = _check_fields(expression)
        errors.extend(field_violations)

        # 3. Look-ahead bias
        lookahead_violations = _check_lookahead(expression)
        errors.extend(lookahead_violations)

        # 4. Complexity check (warnings, not errors)
        complexity_warnings = _check_complexity(expression)
        warnings_list.extend(complexity_warnings)

        # 5. Rolling parameter check (warnings)
        rolling_warnings = _check_rolling_params(expression)
        warnings_list.extend(rolling_warnings)

        # 6. Numerical computability (only if no hard errors)
        if not errors:
            t0 = time.perf_counter()
            computable, comp_err = _check_numerical_computability(engine, expression)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            if not computable:
                errors.append(comp_err or "Numerical computability check failed")
        else:
            elapsed_ms = 0

        ok = len(errors) == 0
        if ok:
            passed_count += 1
        else:
            failed_count += 1

        results.append({
            "name": name,
            "expression": expression,
            "ok": ok,
            "errors": errors,
            "warnings": warnings_list,
            "eval_time_ms": round(elapsed_ms, 2),
        })

    summary = {
        "total": len(factors),
        "passed": passed_count,
        "failed": failed_count,
        "toy_data_shape": [30, 5],
        "results": results,
    }

    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate factor expressions against the factor contract."
    )
    parser.add_argument(
        "--factors", type=str, required=True,
        help="Path to JSON file with factor candidates.",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Output path for validated factors (passed only).",
    )
    parser.add_argument(
        "--run-id", type=str, default=None,
        help="Run identifier. Auto-generated timestamp if not given. Output goes to output/<run-id>/",
    )
    parser.add_argument(
        "--correction-context", action="store_true",
        help="Print LLM correction prompt for failed factors.",
    )
    args = parser.parse_args()

    factors_path = Path(args.factors)
    if not factors_path.is_file():
        print(json.dumps(
            {"error": f"File not found: {args.factors}"}, ensure_ascii=False
        ))
        sys.exit(1)

    try:
        factors = json.loads(factors_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(json.dumps(
            {"error": f"Invalid JSON: {exc}"}, ensure_ascii=False
        ))
        sys.exit(1)

    if not isinstance(factors, list):
        print(json.dumps(
            {"error": "Factor file must contain a JSON array."}, ensure_ascii=False
        ))
        sys.exit(1)

    result = validate_factors(factors)

    # Resolve output directory
    out_dir = _resolve_output("").parent if not args.output else Path(args.output).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Only save passed-only factors — the minimal input for backtest
    passed_factors = [
        {"name": r["name"], "expression": r["expression"],
         "description": next((f.get("description", "") for f in factors if f.get("name") == r["name"]), ""),
         "rationale": next((f.get("rationale", "") for f in factors if f.get("name") == r["name"]), ""),
         "generation": next((f.get("generation", "initial") for f in factors if f.get("name") == r["name"]), "initial"),
         "parent": next((f.get("parent", "") for f in factors if f.get("name") == r["name"]), ""),
         "transformation": next((f.get("transformation", "") for f in factors if f.get("name") == r["name"]), ""),
         }
        for r in result["results"] if r["ok"]
    ]
    passed_path = str(_resolve_output("validated_factors_passed.json"))
    if args.output:
        passed_path = args.output.replace(".json", "_passed.json")
    Path(passed_path).write_text(
        json.dumps(passed_factors, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["passed_output_path"] = passed_path

    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Correction context
    if args.correction_context and result.get("failed", 0) > 0:
        failed = [r for r in result["results"] if not r["ok"]]
        correction = build_correction_prompt(failed)
        print("\n" + "=" * 72)
        print("CORRECTION PROMPT (feed this to your LLM to fix failures)")
        print("=" * 72)
        print(correction)


if __name__ == "__main__":
    main()
