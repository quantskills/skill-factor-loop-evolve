#!/usr/bin/env python3
"""Shared parent-selection logic for factor evolution."""

from __future__ import annotations

import math

from contracts import DUPLICATE_CORRELATION_THRESHOLD

try:
    from knowledge_base import get_parent_diversity_boost
    _HAS_ACTIVE_KB = True
except ImportError:
    _HAS_ACTIVE_KB = False


_CLASSIFICATION_BONUS = {
    "promising": 0.08,
    "weak": 0.0,
    "unstable": -0.05,
    "duplicate": -0.08,
    "overfit": -0.12,
}


def select_parents(
    diagnosis: dict,
    max_parents: int = 3,
    min_parents: int = 1,
    knowledge_base: dict | None = None,
    use_active_kb: bool = True,
    duplicate_threshold: float = DUPLICATE_CORRELATION_THRESHOLD,
) -> list[dict]:
    """Select high-quality, diverse parents for the next generation.

    Actual Sharpe remains the main signal. Tie-breakers reward IC/ICIR and
    promising classification, penalize high turnover/drawdown/overfit labels,
    and avoid highly correlated parents. If too few diverse parents exist, the
    selector relaxes the correlation threshold only enough to satisfy
    ``min_parents``.
    """
    diagnostics = diagnosis.get("diagnostics", [])
    valid = [_with_parent_score(d) for d in diagnostics if _is_valid_parent(d)]

    if use_active_kb and _HAS_ACTIVE_KB and knowledge_base:
        valid = get_parent_diversity_boost(valid, knowledge_base)
        valid = [_with_parent_score(d) for d in valid]

    valid.sort(key=lambda d: d.get("_parent_score", d.get("sharpe") or 0), reverse=True)
    return _select_diverse(
        valid,
        diagnosis.get("correlations", {}),
        max_parents=max_parents,
        min_parents=min(min_parents, max_parents),
        duplicate_threshold=duplicate_threshold,
    )


def _is_valid_parent(diagnostic: dict) -> bool:
    if diagnostic.get("classification") == "invalid":
        return False
    sharpe = diagnostic.get("sharpe")
    if not isinstance(sharpe, (int, float)):
        return False
    return not (math.isnan(sharpe) or math.isinf(sharpe))


def _with_parent_score(diagnostic: dict) -> dict:
    d = dict(diagnostic)
    sharpe = float(d.get("sharpe") or 0.0)
    score = float(d.get("_effective_sharpe", sharpe) or 0.0)
    reasons = [f"S={sharpe:.3f}"]

    classification = d.get("classification", "")
    class_bonus = _CLASSIFICATION_BONUS.get(classification, 0.0)
    if class_bonus:
        score += class_bonus
        reasons.append(f"class={classification}:{class_bonus:+.2f}")

    ic_mean = abs(float(d.get("ic_mean") or 0.0))
    icir = abs(float(d.get("icir") or 0.0))
    if ic_mean:
        ic_bonus = min(ic_mean, 0.05)
        score += ic_bonus
        reasons.append(f"IC:{ic_bonus:+.3f}")
    if icir:
        icir_bonus = min(icir, 1.0) * 0.03
        score += icir_bonus
        reasons.append(f"ICIR:{icir_bonus:+.3f}")

    turnover = d.get("turnover")
    if isinstance(turnover, (int, float)) and turnover > 0.85:
        penalty = min((turnover - 0.85) * 0.25, 0.10)
        score -= penalty
        reasons.append(f"TO:{-penalty:.3f}")

    drawdown = d.get("max_drawdown")
    if isinstance(drawdown, (int, float)) and drawdown < -0.5:
        penalty = min((abs(drawdown) - 0.5) * 0.15, 0.10)
        score -= penalty
        reasons.append(f"DD:{-penalty:.3f}")

    d["_parent_score"] = round(score, 4)
    d["_parent_score_reasons"] = reasons
    return d


def _select_diverse(
    candidates: list[dict],
    correlations: dict[str, float],
    max_parents: int,
    min_parents: int,
    duplicate_threshold: float,
) -> list[dict]:
    if not candidates or max_parents <= 0:
        return []

    selected = _take_uncorrelated(candidates, correlations, max_parents, duplicate_threshold)
    if len(selected) >= min_parents or len(selected) >= min(max_parents, len(candidates)):
        return selected

    for threshold in (0.85, 0.95):
        selected = _take_uncorrelated(candidates, correlations, max_parents, threshold)
        if len(selected) >= min_parents:
            return selected

    selected_names = {p.get("name") for p in selected}
    for candidate in candidates:
        if len(selected) >= min_parents or len(selected) >= max_parents:
            break
        if candidate.get("name") not in selected_names:
            fallback = dict(candidate)
            fallback["_selection_warning"] = "added despite high correlation to satisfy min_parents"
            selected.append(fallback)
            selected_names.add(candidate.get("name"))

    return selected


def _take_uncorrelated(
    candidates: list[dict],
    correlations: dict[str, float],
    max_parents: int,
    threshold: float,
) -> list[dict]:
    selected: list[dict] = []
    for candidate in candidates:
        if len(selected) >= max_parents:
            break
        if not _is_correlated_with_selected(candidate, selected, correlations, threshold):
            picked = dict(candidate)
            picked["_selection_threshold"] = threshold
            selected.append(picked)
    return selected


def _is_correlated_with_selected(
    candidate: dict,
    selected: list[dict],
    correlations: dict[str, float],
    threshold: float,
) -> bool:
    for parent in selected:
        corr = _pair_correlation(candidate.get("name", ""), parent.get("name", ""), correlations)
        if corr is not None and abs(corr) > threshold:
            return True
    return False


def _pair_correlation(
    name_a: str,
    name_b: str,
    correlations: dict[str, float],
) -> float | None:
    for key, value in correlations.items():
        parts = key.split("__vs__")
        if len(parts) != 2:
            continue
        if {parts[0], parts[1]} == {name_a, name_b}:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None
