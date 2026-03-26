from __future__ import annotations

from collections import defaultdict

from bistbot.domain.models import StrategyScore
from bistbot.services.normalization import normalize_scores_by_cluster

MAX_DRAWDOWN_JUNK_THRESHOLD = 0.20
MAX_DRAWDOWN_WEIGHT = 0.30


def is_garbage_strategy(score: StrategyScore) -> bool:
    return score.max_drawdown > MAX_DRAWDOWN_JUNK_THRESHOLD


def compute_composite_score(score: StrategyScore) -> float:
    if is_garbage_strategy(score):
        return float("-inf")

    return (
        0.4 * score.normalized_return
        + 0.2 * score.normalized_win_rate
        + 0.3 * score.normalized_profit_factor
        - MAX_DRAWDOWN_WEIGHT * score.normalized_max_drawdown
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
