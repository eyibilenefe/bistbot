from __future__ import annotations

from datetime import date

from bistbot.domain.enums import StrategyFamily
from bistbot.domain.models import StrategyScore
from bistbot.services.normalization import normalize_scores_by_cluster


def make_score(index: int, total_return: float) -> StrategyScore:
    return StrategyScore(
        strategy_id=f"strategy-{index}",
        cluster_id="cluster-1",
        as_of=date(2026, 3, 25),
        family=StrategyFamily.TREND_FOLLOWING,
        total_return=total_return,
        win_rate=0.5 + index * 0.001,
        profit_factor=1.5 + index * 0.01,
        max_drawdown=0.05 + index * 0.001,
        trade_count=60,
        avg_trade_return=0.01,
        estimated_round_trip_cost=0.003,
        oos_window_trade_counts=[1, 1, 1, 1, 1, 1],
        oos_returns=[0.01, 0.02, 0.03, 0.04],
    )


def test_small_clusters_use_percentile_rank_normalization() -> None:
    scores = normalize_scores_by_cluster(
        [make_score(1, 0.10), make_score(2, 0.20), make_score(3, 0.30)]
    )

    assert [score.normalized_return for score in scores] == [0.0, 0.5, 1.0]


def test_large_clusters_use_winsorized_z_scores() -> None:
    scores = normalize_scores_by_cluster([make_score(index, float(index)) for index in range(30)])

    assert scores[0].normalized_return < 0
    assert scores[-1].normalized_return > 0
