from __future__ import annotations

from datetime import date

import math
import pytest

from bistbot.domain.enums import StrategyFamily
from bistbot.domain.models import StrategyScore
from bistbot.services.scoring import compute_composite_score


def make_score(*, max_drawdown: float) -> StrategyScore:
    score = StrategyScore(
        strategy_id="strategy-1",
        cluster_id="cluster-1",
        as_of=date(2026, 3, 26),
        family=StrategyFamily.TREND_FOLLOWING,
        total_return=0.20,
        win_rate=0.60,
        profit_factor=1.80,
        max_drawdown=max_drawdown,
        trade_count=64,
        avg_trade_return=0.012,
        estimated_round_trip_cost=0.003,
        oos_window_trade_counts=[2, 2, 2, 2, 2, 2],
        oos_returns=[0.01, 0.02, 0.01, 0.03, 0.02, 0.01],
    )
    score.normalized_return = 1.0
    score.normalized_win_rate = 1.0
    score.normalized_profit_factor = 1.0
    score.normalized_max_drawdown = 1.0
    return score


def test_composite_score_penalizes_drawdown_more_aggressively() -> None:
    score = make_score(max_drawdown=0.12)

    composite = compute_composite_score(score)

    assert composite == pytest.approx(0.6)


def test_composite_score_marks_over_20pct_drawdown_as_garbage() -> None:
    score = make_score(max_drawdown=0.25)

    composite = compute_composite_score(score)

    assert math.isinf(composite)
    assert composite < 0
