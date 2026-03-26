from __future__ import annotations

import math
import statistics

from bistbot.domain.enums import StrategyFamily
from bistbot.domain.models import StrategyScore
from bistbot.services.scoring import MAX_DRAWDOWN_JUNK_THRESHOLD

FAMILY_PRIORITY = (
    StrategyFamily.TREND_FOLLOWING,
    StrategyFamily.PULLBACK_MEAN_REVERSION,
    StrategyFamily.BREAKOUT_VOLUME,
)
MIN_STRATEGY_TRADE_COUNT = 12
MIN_ACTIVE_WINDOWS = 2
MIN_AVG_TRADE_COST_MULTIPLE = 1.25


def passes_hybrid_guard(score: StrategyScore) -> bool:
    active_windows = score.oos_window_trade_counts[-6:]
    windows_with_activity = sum(1 for count in active_windows if count > 0)
    return (
        score.trade_count >= MIN_STRATEGY_TRADE_COUNT
        and windows_with_activity >= MIN_ACTIVE_WINDOWS
        and score.avg_trade_return >= MIN_AVG_TRADE_COST_MULTIPLE * score.estimated_round_trip_cost
        and score.max_drawdown <= MAX_DRAWDOWN_JUNK_THRESHOLD
    )


def pairwise_return_correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    if math.isclose(statistics.pstdev(left), 0.0) or math.isclose(statistics.pstdev(right), 0.0):
        return 0.0
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    covariance = sum((l - left_mean) * (r - right_mean) for l, r in zip(left, right)) / len(left)
    return covariance / (statistics.pstdev(left) * statistics.pstdev(right))


def select_active_strategies(
    strategy_scores: list[StrategyScore],
    *,
    max_active: int = 3,
    max_correlation: float = 0.75,
) -> list[StrategyScore]:
    eligible = [score for score in strategy_scores if passes_hybrid_guard(score)]
    eligible.sort(key=lambda score: score.composite_score, reverse=True)

    selected: list[StrategyScore] = []
    used_families: set[StrategyFamily] = set()

    for family in FAMILY_PRIORITY:
        family_candidates = [
            score
            for score in eligible
            if score.family == family and score.family not in used_families
        ]
        for candidate in family_candidates:
            is_diversified = all(
                pairwise_return_correlation(candidate.oos_returns, existing.oos_returns) < max_correlation
                for existing in selected
            )
            if not is_diversified:
                continue
            selected.append(candidate)
            used_families.add(candidate.family)
            break
        if len(selected) >= max_active:
            break

    return selected[:max_active]
