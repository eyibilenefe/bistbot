from __future__ import annotations

from collections import defaultdict

from bistbot.domain.models import StrategyScore
from bistbot.services.normalization import normalize_scores_by_cluster

SOFT_DRAWDOWN_THRESHOLD = 0.20
MAX_DRAWDOWN_JUNK_THRESHOLD = 0.30
MAX_DRAWDOWN_WEIGHT = 0.18
EXCESS_DRAWDOWN_PENALTY_WEIGHT = 0.60


def is_garbage_strategy(score: StrategyScore) -> bool:
    return score.max_drawdown > MAX_DRAWDOWN_JUNK_THRESHOLD


def excess_drawdown_penalty(max_drawdown: float) -> float:
    excess_drawdown = max(max_drawdown - SOFT_DRAWDOWN_THRESHOLD, 0.0)
    penalty_band = MAX_DRAWDOWN_JUNK_THRESHOLD - SOFT_DRAWDOWN_THRESHOLD
    if excess_drawdown <= 0 or penalty_band <= 0:
        return 0.0
    return EXCESS_DRAWDOWN_PENALTY_WEIGHT * min(excess_drawdown / penalty_band, 1.0)


def compute_composite_score(score: StrategyScore) -> float:
    if is_garbage_strategy(score):
        return float("-inf")

    return (
        0.4 * score.normalized_return
        + 0.2 * score.normalized_win_rate
        + 0.3 * score.normalized_profit_factor
        - MAX_DRAWDOWN_WEIGHT * score.normalized_max_drawdown
        - excess_drawdown_penalty(score.max_drawdown)
    )


def score_clusters(strategy_scores: list[StrategyScore]) -> list[StrategyScore]:
    grouped_scores: dict[str, list[StrategyScore]] = defaultdict(list)
    for score in strategy_scores:
        grouped_scores[score.cluster_id].append(score)

    scored_results: list[StrategyScore] = []
    for cluster_scores in grouped_scores.values():
        normalized = normalize_scores_by_cluster(cluster_scores)
        for score in normalized:
            score.composite_score = compute_composite_score(score)
        scored_results.extend(sorted(normalized, key=lambda item: item.composite_score, reverse=True))
    return scored_results
