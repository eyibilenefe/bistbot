from __future__ import annotations

from datetime import date

from bistbot.domain.enums import StrategyFamily
from bistbot.domain.models import StrategyScore
from bistbot.services.strategy_selection import select_active_strategies


def make_score(
    strategy_id: str,
    family: StrategyFamily,
    composite_score: float,
    oos_returns: list[float],
    *,
    max_drawdown: float = 0.10,
) -> StrategyScore:
    score = StrategyScore(
        strategy_id=strategy_id,
        cluster_id="cluster-1",
        as_of=date(2026, 3, 25),
        family=family,
        total_return=0.30,
        win_rate=0.58,
        profit_factor=1.70,
        max_drawdown=max_drawdown,
        trade_count=60,
        avg_trade_return=0.010,
        estimated_round_trip_cost=0.003,
        oos_window_trade_counts=[1, 1, 1, 1, 1, 1],
        oos_returns=oos_returns,
    )
    score.composite_score = composite_score
    return score


def test_strategy_selection_keeps_family_diversity_and_correlation_limits() -> None:
    strategies = [
        make_score(
            "trend-a",
            StrategyFamily.TREND_FOLLOWING,
            0.95,
            [0.01, 0.02, 0.03, 0.04],
        ),
        make_score(
            "pullback-a",
            StrategyFamily.PULLBACK_MEAN_REVERSION,
            0.91,
            [0.04, 0.03, 0.02, 0.01],
        ),
        make_score(
            "breakout-high-corr",
            StrategyFamily.BREAKOUT_VOLUME,
            0.89,
            [0.02, 0.04, 0.06, 0.08],
        ),
        make_score(
            "breakout-diversified",
            StrategyFamily.BREAKOUT_VOLUME,
            0.80,
            [0.03, 0.01, -0.01, 0.02],
        ),
        make_score(
            "trend-high-dd",
            StrategyFamily.TREND_FOLLOWING,
            9.99,
            [0.01, 0.03, 0.01, 0.02],
            max_drawdown=0.31,
        ),
    ]

    selected = select_active_strategies(strategies)

    assert [score.strategy_id for score in selected] == [
        "trend-a",
        "pullback-a",
        "breakout-diversified",
    ]
