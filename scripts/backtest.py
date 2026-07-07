#!/usr/bin/env python3
"""Real-data backtest engine for skill-factor-loop-evolve.

Runs a consistent cross-sectional long-short backtest on validated factors.
Uses panda_data API to retrieve real A-share market OHLCV data. Credentials
are read from a ``.env`` file in the skill root directory.

Data window: configurable via config.json (default: CSI 300, 2024-2025).
Universe: CSI 300 (000300) by default, configurable via --universe.

Usage::

    python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json
    python scripts/backtest.py --factors validated_factors_passed.json --universe 000905 --output backtest_results_all.json
    python scripts/backtest.py --factors validated.json --cost-bps 3 --holding-days 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ── Load .env from skill root ────────────────────────────────────────────────
_SKILL_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _SKILL_ROOT / ".env"

if _ENV_PATH.is_file():
    with open(_ENV_PATH, "r", encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key = _key.strip()
                _val = _val.strip().strip('"').strip("'")
                if _key not in os.environ:
                    os.environ[_key] = _val

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts import DEFAULT_BACKTEST_CONFIG  # noqa: E402
from contracts import output_path as _resolve_output  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# PandaData Market Data Fetcher
# ═══════════════════════════════════════════════════════════════════════════════

_panda_data = None
_panda_init_attempted = False


def _init_pandadata() -> None:
    """Lazily initialize PandaData. Called only when actually fetching data."""
    global _panda_data, _panda_init_attempted
    if _panda_init_attempted:
        return
    _panda_init_attempted = True

    try:
        import panda_data  # noqa: F811
    except ImportError:
        print(
            "[FATAL] panda_data is not installed. Install it with:\n"
            "    pip install panda_data\n"
            "This skill REQUIRES panda_data for real A-share market data.",
            file=sys.stderr,
        )
        sys.exit(1)

    _PANDA_USERNAME = os.environ.get("PANDA_AI_USERNAME", "")
    _PANDA_PASSWORD = os.environ.get("PANDA_AI_PASSWORD", "")
    _PANDA_BASE_URL = os.environ.get("PANDA_AI_BASE_URL", "http://pandadata.pandaaiquant.com")

    if not _PANDA_USERNAME or not _PANDA_PASSWORD:
        print(
            "[FATAL] PandaData credentials not found in .env.\n"
            "Set PANDA_AI_USERNAME and PANDA_AI_PASSWORD in the .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        panda_data.init_token(
            username=_PANDA_USERNAME,
            password=_PANDA_PASSWORD,
            base_url=_PANDA_BASE_URL,
        )
        _panda_data = panda_data
    except Exception as e:
        print(f"[FATAL] PandaData init failed: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_market_data_from_pandadata(
    start_date: str,
    end_date: str,
    indicator: str = "000300",
    exclude_st: bool = True,
) -> pd.DataFrame | None:
    """Fetch A-share daily OHLCV data from PandaData.

    Args:
        start_date: Start date as YYYYMMDD string.
        end_date: End date as YYYYMMDD string.
        indicator: Stock universe index code (default: 000300 = CSI 300).
        exclude_st: Whether to exclude ST stocks.

    Returns:
        DataFrame with columns: date, symbol, open, high, low, close, volume, amount.
        Returns None on failure.
    """
    if _panda_data is None:
        _init_pandadata()
    if _panda_data is None:
        return None

    try:
        raw = _panda_data.get_market_data(
            start_date=start_date,
            end_date=end_date,
            type="stock",
            indicator=indicator,
            st=not exclude_st,
        )

        if raw is None or raw.empty:
            print(f"[WARN] PandaData returned empty data for {start_date}–{end_date}, indicator={indicator}")
            return None

        df = raw.copy()

        # Normalize column names to lowercase
        col_map = {}
        for c in df.columns:
            cl = c.lower().strip()
            if cl in ("open", "high", "low", "close", "volume"):
                col_map[c] = cl
        if col_map:
            df = df.rename(columns=col_map)

        # Compute amount from close * volume if not present
        if "amount" not in df.columns:
            close_col = "close" if "close" in df.columns else None
            volume_col = "volume" if "volume" in df.columns else None
            if close_col and volume_col:
                df["amount"] = df[close_col].astype(float) * df[volume_col].astype(float)
            else:
                df["amount"] = 0.0

        # Ensure required columns exist
        required = ["date", "symbol", "open", "high", "low", "close", "volume", "amount"]
        for col in required:
            if col not in df.columns:
                if col == "amount":
                    df[col] = 0.0
                else:
                    print(f"[WARN] Missing column in PandaData response: {col}")
                    return None

        df = df[required].copy()
        df["date"] = df["date"].astype(str)
        df["symbol"] = df["symbol"].astype(str)
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values(["date", "symbol"]).reset_index(drop=True)

        n_dates = df["date"].nunique()
        n_symbols = df["symbol"].nunique()
        print(f"[INFO] PandaData: {n_dates} dates × {n_symbols} symbols fetched "
              f"({start_date}–{end_date}, indicator={indicator})", file=sys.stderr)

        return df

    except Exception as e:
        print(f"[ERROR] PandaData fetch failed: {e}", file=sys.stderr)
        return None


def make_synthetic_market_data(
    num_dates: int = 500,
    num_symbols: int = 100,
    seed: int = 42,
) -> pd.DataFrame:
    """Fallback: generate synthetic OHLCV data for backtesting."""
    rng = np.random.default_rng(seed)
    symbols = [f"STK{i:04d}" for i in range(num_symbols)]
    dates = pd.date_range("2022-01-01", periods=num_dates, freq="B")

    n_factors = 3
    factor_returns = rng.normal(0.0002, 0.01, (num_dates, n_factors))
    factor_loadings = rng.normal(0, 1, (num_symbols, n_factors))

    rows: list[dict[str, Any]] = []
    base_prices = rng.uniform(10, 200, num_symbols)
    prices = base_prices.copy()

    for d_idx, date in enumerate(dates):
        sys_ret = factor_loadings @ factor_returns[d_idx]
        idio_ret = rng.normal(0, 0.015, num_symbols)
        daily_rets = sys_ret + idio_ret
        prices = prices * (1 + daily_rets)
        prices = np.maximum(prices, 1.0)

        for s_idx, sym in enumerate(symbols):
            c = prices[s_idx]
            daily_range = c * rng.uniform(0.005, 0.03)
            o = c * (1 + rng.normal(0, 0.003))
            h = max(o, c) + daily_range * rng.uniform(0, 0.5)
            l = min(o, c) - daily_range * rng.uniform(0, 0.5)
            v = max(1000, rng.integers(50_000, 20_000_000))
            rows.append({
                "date": date.strftime("%Y%m%d"),
                "symbol": sym,
                "open": round(float(o), 2),
                "high": round(float(h), 2),
                "low": round(float(l), 2),
                "close": round(float(c), 2),
                "volume": float(v),
                "amount": round(float(c * v), 2),
            })

    print("[WARN] Using synthetic data (panda_data unavailable)", file=sys.stderr)
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════════
# Toy Factor Evaluator (for backtest)
# ═══════════════════════════════════════════════════════════════════════════════

class BacktestFactorEngine:
    """Evaluates factor expressions on market data for backtesting."""

    def __init__(self, data: pd.DataFrame):
        self._pivoted: dict[str, pd.DataFrame] = {}
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            pivot = data.pivot_table(
                index="date", columns="symbol", values=col, aggfunc="first"
            )
            pivot.index = pd.to_datetime(pivot.index, format="%Y%m%d")
            pivot = pivot.sort_index()
            self._pivoted[col] = pivot

    def evaluate(self, expression: str) -> pd.DataFrame | None:
        """Evaluate factor expression on full dataset."""
        try:
            local_vars = {field: self._pivoted[field] for field in self._pivoted}
            local_vars.update({
                "rank": lambda x: x.rank(axis=1, pct=True),
                "zscore": lambda x: (x - x.mean(axis=1)).div(
                    x.std(axis=1).replace(0, 1e-8), axis=0
                ),
                "scale": lambda x, a=1.0: x.div(
                    x.abs().sum(axis=1).replace(0, 1e-8), axis=0
                ) * a,
                "ts_rank": lambda x, n: x.rolling(n, min_periods=max(1, n // 2)).apply(
                    lambda s: s.rank(pct=True).iloc[-1], raw=False
                ),
                "ts_zscore": lambda x, n: (x - x.rolling(n, min_periods=max(1, n // 2)).mean())
                / x.rolling(n, min_periods=max(1, n // 2)).std().replace(0, 1e-8),
                "ts_mean": lambda x, n: x.rolling(n, min_periods=max(1, n // 2)).mean(),
                "ts_std": lambda x, n: x.rolling(n, min_periods=max(1, n // 2)).std(),
                "ts_max": lambda x, n: x.rolling(n, min_periods=max(1, n // 2)).max(),
                "ts_min": lambda x, n: x.rolling(n, min_periods=max(1, n // 2)).min(),
                "ts_sum": lambda x, n: x.rolling(n, min_periods=max(1, n // 2)).sum(),
                "ts_argmax": lambda x, n: x.rolling(n, min_periods=max(1, n // 2)).apply(
                    lambda s: n - 1 - s.values.argmax() if len(s) > 0 else 0, raw=False
                ),
                "ts_argmin": lambda x, n: x.rolling(n, min_periods=max(1, n // 2)).apply(
                    lambda s: n - 1 - s.values.argmin() if len(s) > 0 else 0, raw=False
                ),
                "correlation": lambda x, y, n: x.rolling(
                    n, min_periods=max(1, n // 2)
                ).corr(y),
                "covariance": lambda x, y, n: x.rolling(
                    n, min_periods=max(1, n // 2)
                ).cov(y),
                "decay_linear": lambda x, n: x.rolling(
                    n, min_periods=max(1, n // 2)
                ).apply(
                    lambda s: np.average(s, weights=np.arange(1, len(s) + 1))
                    if len(s) > 0 else np.nan,
                    raw=True,
                ),
                "delay": lambda x, n: x.shift(n),
                "delta": lambda x, n: x - x.shift(n),
                "returns": lambda x, n=1: x.pct_change(n),
                "adv": lambda n: self._pivoted["volume"].rolling(
                    n, min_periods=max(1, n // 2)
                ).mean(),
                "sign": np.sign,
                "log": np.log,
                "abs": np.abs,
                "power": lambda x, n: x ** n,
                "signed_power": lambda x, n: np.sign(x) * (np.abs(x) ** n),
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


# ═══════════════════════════════════════════════════════════════════════════════
# Backtest Engine
# ═══════════════════════════════════════════════════════════════════════════════

class FixedBacktestEngine:
    """Fixed-configuration cross-sectional long-short backtest.

    Goes long the top ``long_pct`` fraction of stocks and short the bottom
    ``short_pct`` fraction. Both default to 20% (top/bottom quintile).
    """

    def __init__(
        self,
        cost_bps: float = 5.0,
        holding_days: int = 5,
        n_quantiles: int = 5,
        long_pct: float = 0.2,
        short_pct: float = 0.2,
        lookback_min: int = 252,
    ):
        self.cost_bps = cost_bps
        self.holding_days = holding_days
        self.n_quantiles = n_quantiles
        self.long_pct = long_pct
        self.short_pct = short_pct
        self.lookback_min = lookback_min

    def run(
        self,
        factor_values: pd.DataFrame,
        returns: pd.DataFrame,
    ) -> dict:
        """Run backtest for a single factor.

        Long top ``long_pct`` fraction, short bottom ``short_pct`` fraction.
        Portfolio return = long_leg - short_leg - costs.

        Returns a dict with summary metrics AND raw trading data.
        """
        common_dates = factor_values.index.intersection(returns.index)
        common_symbols = factor_values.columns.intersection(returns.columns)

        if len(common_dates) < self.lookback_min:
            return {"error": f"Insufficient data: {len(common_dates)} < {self.lookback_min}"}
        if len(common_symbols) < 10:
            return {"error": f"Insufficient symbols: {len(common_symbols)} < 10"}

        fv = factor_values.loc[common_dates, common_symbols]
        ret = returns.loc[common_dates, common_symbols]

        rebalance_dates = common_dates[:: self.holding_days]
        if len(rebalance_dates) < 10:
            return {"error": f"Too few rebalance dates: {len(rebalance_dates)}"}

        # Number of stocks for long/short legs.
        n_stocks = len(common_symbols)
        n_long = max(1, int(n_stocks * self.long_pct))
        n_short = max(1, int(n_stocks * self.short_pct))

        portfolio_returns = []
        long_returns_list = []
        short_returns_list = []
        positions_log = []
        prev_long_symbols: set = set()
        prev_short_symbols: set = set()
        turnover_values: list[float] = []

        for i, date in enumerate(rebalance_dates[:-1]):
            scores = fv.loc[date].dropna()
            if len(scores) < n_long + n_short:
                continue

            top_scores = scores.nlargest(n_long)
            bottom_scores = scores.nsmallest(n_short)
            if top_scores.empty or bottom_scores.empty:
                continue

            # Use the forward return from the rebalance date itself (no look-ahead)
            # forward_returns.loc[date] = return from date → date + holding_days
            rebalance_idx = common_dates.get_loc(date)
            end_idx = min(rebalance_idx + self.holding_days, len(common_dates) - 1)
            if end_idx <= rebalance_idx:
                continue

            fwd_ret = ret.iloc[rebalance_idx]
            if isinstance(fwd_ret, pd.Series):
                fwd_ret = fwd_ret.dropna()
            if fwd_ret.empty:
                continue

            # Long leg: top stocks
            long_symbols = set(top_scores.index)
            long_ret = fwd_ret[list(long_symbols & set(fwd_ret.index))].mean()
            # Short leg: bottom stocks (we profit when they go down)
            short_symbols = set(bottom_scores.index)
            short_ret = fwd_ret[list(short_symbols & set(fwd_ret.index))].mean()
            # Long-short spread minus costs (cost on both legs)
            cost = self.cost_bps / 10000 * 4  # round-trip × 2 legs
            period_return = long_ret - short_ret - cost

            portfolio_returns.append(period_return)
            long_returns_list.append(long_ret)
            short_returns_list.append(short_ret)

            # Compute actual turnover: fraction of positions changed vs. previous
            if prev_long_symbols or prev_short_symbols:
                prev_all = prev_long_symbols | prev_short_symbols
                curr_all = long_symbols | short_symbols
                if len(prev_all | curr_all) > 0:
                    turnover_i = 1 - len(prev_all & curr_all) / len(prev_all | curr_all)
                    turnover_values.append(turnover_i)
            prev_long_symbols = long_symbols
            prev_short_symbols = short_symbols

            # Log positions
            positions_log.append({
                "date": str(date),
                "long_symbols": top_scores.index.tolist()[:20],
                "long_scores": [round(s, 6) for s in top_scores.tolist()[:20]],
                "short_symbols": bottom_scores.index.tolist()[:20],
                "short_scores": [round(s, 6) for s in bottom_scores.tolist()[:20]],
            })

        if len(portfolio_returns) < 10:
            return {"error": f"Too few portfolio periods: {len(portfolio_returns)}"}

        portfolio_returns = np.array(portfolio_returns)

        mean_ret = float(np.mean(portfolio_returns))
        std_ret = float(np.std(portfolio_returns))
        sharpe = float(mean_ret / std_ret * np.sqrt(252 / self.holding_days)) if std_ret > 0 else 0.0

        n_periods = len(portfolio_returns)
        total_return = float(np.prod(1 + portfolio_returns) - 1)
        years = n_periods * self.holding_days / 252
        # Clamp for annualization: if total_return <= -1, annual_return = -1
        if total_return <= -1:
            annual_return = -1.0
        else:
            annual_return = float((1 + total_return) ** (1 / max(years, 0.25)) - 1)

        # Drawdown: clamp individual period returns to avoid < -100% per period
        clamped_returns = np.clip(portfolio_returns, -0.99, None)
        cum = np.cumprod(1 + clamped_returns)
        running_max = np.maximum.accumulate(cum)
        drawdowns = (cum - running_max) / np.maximum(running_max, 1e-8)
        max_drawdown = float(drawdowns.min())

        # Real turnover: average fraction of positions changed between rebalances
        turnover = float(np.mean(turnover_values)) if turnover_values else 0.0
        coverage = self.long_pct + self.short_pct  # fraction of universe covered

        ic_values = []
        for date in common_dates:
            if date in fv.index and date in ret.index:
                fwd = ret.loc[date]
                scores = fv.loc[date]
                common = fwd.dropna().index.intersection(scores.dropna().index)
                if len(common) > 10:
                    ic = np.corrcoef(
                        scores[common].rank(), fwd[common].rank()
                    )[0, 1]
                    if not np.isnan(ic):
                        ic_values.append(ic)

        ic_mean = float(np.mean(ic_values)) if ic_values else 0.0
        ic_std = float(np.std(ic_values)) if ic_values else 0.0
        icir = float(ic_mean / ic_std) if ic_std > 0 else 0.0

        long_return = float(np.mean(long_returns_list)) if long_returns_list else 0.0
        short_return = float(np.mean(short_returns_list)) if short_returns_list else 0.0

        return {
            "mean_return": round(mean_ret, 6),
            "std_return": round(std_ret, 6),
            "sharpe": round(sharpe, 4),
            "annual_return": round(annual_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "turnover": round(turnover, 4),
            "coverage": round(coverage, 4),
            "ic_mean": round(ic_mean, 4),
            "ic_std": round(ic_std, 4),
            "icir": round(icir, 4),
            "long_return": round(long_return, 4),
            "short_return": round(short_return, 4),
            "n_periods": n_periods,
            # Trading data for detailed analysis
            "_trading_data": {
                "portfolio_returns": [round(r, 6) for r in portfolio_returns.tolist()],
                "ic_series": [round(ic, 6) for ic in ic_values],
                "positions_log": positions_log,
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CSV Trading Data Export
# ═══════════════════════════════════════════════════════════════════════════════

def _save_trading_csv(td_dir: Path, trading_data_all: dict) -> None:
    """Save trading data as CSV files for easy analysis in Excel/Pandas.

    Produces three CSV files:
    - ``portfolio_returns.csv``: factor_name, period, return
    - ``ic_series.csv``: factor_name, period, ic
    - ``positions.csv``: factor_name, date, symbol, score
    """
    # ── Portfolio returns ──────────────────────────────────────────────
    pr_rows = []
    for factor_name, td in trading_data_all.items():
        for i, ret in enumerate(td.get("portfolio_returns", [])):
            pr_rows.append({
                "factor": factor_name,
                "period": i,
                "return": ret,
            })
    if pr_rows:
        pd.DataFrame(pr_rows).to_csv(td_dir / "portfolio_returns.csv", index=False)

    # ── IC series ──────────────────────────────────────────────────────
    ic_rows = []
    for factor_name, td in trading_data_all.items():
        for i, ic in enumerate(td.get("ic_series", [])):
            ic_rows.append({
                "factor": factor_name,
                "period": i,
                "ic": ic,
            })
    if ic_rows:
        pd.DataFrame(ic_rows).to_csv(td_dir / "ic_series.csv", index=False)

    # ── Positions log ──────────────────────────────────────────────────
    pos_rows = []
    for factor_name, td in trading_data_all.items():
        for entry in td.get("positions_log", []):
            date = entry.get("date", "")
            # Long positions
            for sym, score in zip(entry.get("long_symbols", []), entry.get("long_scores", [])):
                pos_rows.append({
                    "factor": factor_name,
                    "date": date,
                    "symbol": sym,
                    "score": score,
                    "side": "long",
                })
            # Short positions
            for sym, score in zip(entry.get("short_symbols", []), entry.get("short_scores", [])):
                pos_rows.append({
                    "factor": factor_name,
                    "date": date,
                    "symbol": sym,
                    "score": score,
                    "side": "short",
                })
    if pos_rows:
        pd.DataFrame(pos_rows).to_csv(td_dir / "positions.csv", index=False)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _default_start_date() -> str:
    return DEFAULT_BACKTEST_CONFIG.get("start_date", "20240101")


def _default_end_date() -> str:
    return DEFAULT_BACKTEST_CONFIG.get("end_date", "20251231")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fixed backtest on validated factors using panda_data market data."
    )
    parser.add_argument("--factors", type=str, required=True,
                        help="Path to validated factors JSON.")
    parser.add_argument("--output", type=str, default="",
                        help="Output path for backtest results (default: output/<run-id>/backtest_results_all.json).")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Run identifier. Auto-generated timestamp if not given.")
    parser.add_argument("--data", type=str, default="",
                        help="Optional path to OHLCV CSV data (overrides panda_data).")
    parser.add_argument("--start-date", type=str, default=_default_start_date(),
                        help="Start date YYYYMMDD (default: 20240101).")
    parser.add_argument("--end-date", type=str, default=_default_end_date(),
                        help="End date YYYYMMDD (default: 20251231).")
    parser.add_argument("--universe", type=str, default=DEFAULT_BACKTEST_CONFIG.get("universe", "000300"),
                        help="Stock universe index code (default from config: 000300 = CSI 300, 000905 = CSI 500, 000016 = SSE 50, 000852 = CSI 1000).")
    parser.add_argument("--include-st", action="store_true",
                        help="Include ST stocks (excluded by default per config).")
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_BACKTEST_CONFIG.get("cost_bps", 5.0),
                        help="Transaction cost in bps (default from config).")
    parser.add_argument("--holding-days", type=int, default=DEFAULT_BACKTEST_CONFIG.get("holding_days", 5),
                        help="Holding period in days (default from config).")
    parser.add_argument("--n-quantiles", type=int, default=DEFAULT_BACKTEST_CONFIG.get("n_quantiles", 5),
                        help="Number of quantile groups (default from config).")
    parser.add_argument("--long-pct", type=float, default=DEFAULT_BACKTEST_CONFIG.get("long_pct", 0.2),
                        help="Fraction of stocks to go long (default from config).")
    parser.add_argument("--short-pct", type=float, default=DEFAULT_BACKTEST_CONFIG.get("short_pct", 0.2),
                        help="Fraction of stocks to go short (default from config).")
    parser.add_argument("--lookback-min-days", type=int, default=DEFAULT_BACKTEST_CONFIG.get("lookback_min_days", 252),
                        help="Minimum common dates required for a backtest (default from config).")
    args = parser.parse_args()

    universe = args.universe

    factors_path = Path(args.factors)
    if not factors_path.is_file():
        print(json.dumps({"error": f"File not found: {args.factors}"}, ensure_ascii=False))
        sys.exit(1)

    factors = json.loads(factors_path.read_text(encoding="utf-8-sig"))
    if not isinstance(factors, list):
        print(json.dumps({"error": "Factor file must contain a JSON array."}, ensure_ascii=False))
        sys.exit(1)

    # Load data: CSV file or PandaData
    if args.data:
        data_path = Path(args.data)
        if not data_path.is_file():
            print(json.dumps({"error": f"CSV data file not found: {args.data}"}, ensure_ascii=False))
            sys.exit(1)
        data = pd.read_csv(data_path)
        data_source = f"csv ({data_path})"
    else:
        data = fetch_market_data_from_pandadata(
            start_date=args.start_date,
            end_date=args.end_date,
            indicator=universe,
            exclude_st=not args.include_st,
        )
        if data is None:
            print(
                "[FATAL] PandaData returned empty data. "
                "Check your credentials, network, and date range.",
                file=sys.stderr,
            )
            sys.exit(1)
        data_source = f"panda_data ({universe}, {args.start_date}–{args.end_date})"

    print(f"[INFO] Data source: {data_source}", file=sys.stderr)
    print(f"[INFO] Data shape: {data.shape[0]} rows x {data.shape[1]} cols", file=sys.stderr)

    engine = BacktestFactorEngine(data)
    bt = FixedBacktestEngine(
        cost_bps=args.cost_bps,
        holding_days=args.holding_days,
        n_quantiles=args.n_quantiles,
        long_pct=args.long_pct,
        short_pct=args.short_pct,
        lookback_min=args.lookback_min_days,
    )

    close_pivot = data.pivot_table(
        index="date", columns="symbol", values="close", aggfunc="first"
    )
    close_pivot.index = pd.to_datetime(close_pivot.index, format="%Y%m%d")
    close_pivot = close_pivot.sort_index()
    forward_returns = close_pivot.pct_change(args.holding_days).shift(-args.holding_days)

    # Resolve output path early
    top_out = args.output if args.output else str(_resolve_output("backtest_results_all.json"))
    out_dir = Path(top_out).parent
    td_dir = out_dir / "trading_data"
    td_dir.mkdir(parents=True, exist_ok=True)

    # ── Load evolution file (once) for iteration tracking & later update ─
    evo_path = out_dir / "candidate_evolution.json"
    if evo_path.is_file():
        try:
            evo = json.loads(evo_path.read_text(encoding="utf-8-sig"))
        except Exception:
            evo = {"nodes": [], "edges": [], "run_iteration": 0}
    else:
        evo = {"nodes": [], "edges": [], "run_iteration": 0}

    # ── Determine current iteration from accumulated results ──────────
    # The backtest_results_all.json tracks completed iterations.
    # Current iteration = (# completed iterations) + 1.
    all_bt_path = Path(top_out)
    if all_bt_path.is_file():
        try:
            all_prev = json.loads(all_bt_path.read_text(encoding="utf-8-sig"))
            prev_count = len(all_prev.get("iterations", []))
        except Exception:
            prev_count = 0
    else:
        prev_count = 0
    current_iter = prev_count + 1

    factor_results = []
    trading_data_all = {}
    passed = 0
    failed = 0

    for factor in factors:
        name = factor.get("name", "unnamed")
        expression = factor.get("expression", "")

        factor_values = engine.evaluate(expression)
        if factor_values is None:
            factor_results.append({
                "name": name, "expression": expression,
                "error": "Evaluation failed",
                "_iteration": current_iter,
            })
            failed += 1
            continue

        bt_result = bt.run(factor_values, forward_returns)
        if "error" in bt_result:
            factor_results.append({
                "name": name, "expression": expression,
                "error": bt_result["error"],
                "_iteration": current_iter,
            })
            failed += 1
        else:
            # Extract trading data before stripping
            td = bt_result.pop("_trading_data", {})
            if td:
                trading_data_all[name] = td
            factor_results.append({
                "name": name, "expression": expression,
                **bt_result,
                "_iteration": current_iter,
            })
            passed += 1

    if trading_data_all:
        # ── Save as CSV ──────────────────────────────────────────────────
        _save_trading_csv(td_dir, trading_data_all)
        print(f"[INFO] Trading data (CSV) saved to {td_dir}", file=sys.stderr)

    # ── Update evolution file with actual Sharpe values ──────────────────
    existing_ids = {n["id"] for n in evo.get("nodes", [])}

    for fr in factor_results:
        name = fr.get("name", "")
        if "error" in fr:
            continue
        # Update existing node or add new one (for initial candidates)
        found = False
        for node in evo.get("nodes", []):
            if node["id"] == name:
                node["sharpe"] = fr.get("sharpe", 0)
                node["ic_mean"] = fr.get("ic_mean")
                node["turnover"] = fr.get("turnover")
                node["annual_return"] = fr.get("annual_return")
                node["max_drawdown"] = fr.get("max_drawdown")
                # Keep existing classification if set by generate_candidates
                if not node.get("classification"):
                    node["classification"] = "backtested"
                found = True
                break
        if not found and name not in existing_ids:
            # Initial candidates that were never added by generate_candidates
            evo.setdefault("nodes", []).append({
                "id": name,
                "expression": fr.get("expression", name),
                "label": fr.get("expression", name)[:100],
                "sharpe": fr.get("sharpe", 0),
                "ic_mean": fr.get("ic_mean"),
                "turnover": fr.get("turnover"),
                "annual_return": fr.get("annual_return"),
                "max_drawdown": fr.get("max_drawdown"),
                "iteration": 1,
                "classification": "backtested",
            })
            existing_ids.add(name)

    evo_path.write_text(
        json.dumps(evo, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Accumulate all backtest results across iterations ────────────────
    # all_prev is already loaded above (for iteration counting); reload is safe
    if all_bt_path.is_file():
        try:
            all_prev = json.loads(all_bt_path.read_text(encoding="utf-8-sig"))
        except Exception:
            all_prev = {"iterations": []}
    else:
        all_prev = {"iterations": []}
    all_prev["iterations"].append({
        "iteration": current_iter,
        "passed": passed,
        "failed": failed,
        "total": len(factors),
        "data_shape": [len(close_pivot), len(close_pivot.columns)],
        "factor_results": factor_results,
    })
    all_bt_path.write_text(
        json.dumps(all_prev, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    output = {
        "backtest_config": {
            "cost_bps": args.cost_bps,
            "holding_days": args.holding_days,
            "n_quantiles": args.n_quantiles,
            "long_pct": args.long_pct,
            "short_pct": args.short_pct,
            "lookback_min_days": args.lookback_min_days,
            "data_source": data_source,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "universe": args.universe,
            "run_id": None,
        },
        "total": len(factors),
        "passed": passed,
        "failed": failed,
        "data_shape": [len(close_pivot), len(close_pivot.columns)],
        "factor_results": factor_results,
        "correlations": {},
    }

    # ── Print summary to stdout (pipeline consumers read this) ─────────
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
