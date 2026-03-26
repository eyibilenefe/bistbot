from __future__ import annotations

import math
import statistics

from bistbot.domain.models import StrategyScore


def winsorized_z_scores(values: list[float], *, trim_ratio: float = 0.05) -> list[float]:
    if not values:
        return []
    if len(values) == 1:
        return [0.0]

    sorted_values = sorted(values)
    lower_index = int((len(sorted_values) - 1) * trim_ratio)
    upper_index = int((len(sorted_values) - 1) * (1 - trim_ratio))
    lower_bound = sorted_values[lower_index]
    upper_bound = sorted_values[upper_index]
    winsorized = [min(max(value, lower_bound), upper_bound) for value in values]
    mean = statistics.fmean(winsorized)
    std_dev = statistics.pstdev(winsorized)
    if math.isclose(std_dev, 0.0):
        return [0.0 for _ in winsorized]
    return [(value - mean) / std_dev for value in winsorized]


def percentile_rank_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    if len(values) == 1:
        return [1.0]

    sorted_pairs = sorted(enumerate(values), key=lambda item: item[1])
    scores = [0.0] * len(values)
    cursor = 0
    while cursor < len(sorted_pairs):
        run_end = cursor
        while (
            run_end + 1 < len(sorted_pairs)
            and sorted_pairs[run_end + 1][1] == sorted_pairs[cursor][1]
        ):
            run_end += 1
        avg_rank = (cursor + run_end) / 2
        percentile = avg_rank / (len(sorted_pairs) - 1)
        for position in range(cursor, run_end + 1):
            original_index = sorted_pairs[position][0]
            scores[original_index] = percentile
        cursor = run_end + 1
    return scores


def normalize_scores_by_cluster(
    strategy_scores: list[StrategyScore], *, zscore_min_n: int = 30
) -> list[StrategyScore]:
    if not strategy_scores:
        return []

    use_zscore = len(strategy_scores) >= zscore_min_n
    normalizer = winsorized_z_scores if use_zscore else percentile_rank_scores

    returns = normalizer([score.total_return for score in strategy_scores])
    win_rates = normalizer([score.win_rate for score in strategy_scores])
    profit_factors = normalizer([score.profit_factor for score in strategy_scores])
    drawdowns = normalizer([score.max_drawdown for score in strategy_scores])

    normalized_scores: list[StrategyScore] = []
    for index, score in enumerate(strategy_scores):
        score.normalized_return = returns[index]
        score.normalized_win_rate = win_rates[index]
        score.normalized_profit_factor = profit_factors[index]
        score.normalized_max_drawdown = drawdowns[index]
        normalized_scores.append(score)
    return normalized_scores
