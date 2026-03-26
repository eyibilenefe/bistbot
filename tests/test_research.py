from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bistbot.domain.enums import StrategyFamily
from bistbot.domain.models import PriceBar
from bistbot.services.research import compute_indicators, simulate_strategy


def build_breakout_bars() -> list[PriceBar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[PriceBar] = []
    close = 100.0

    for index in range(260):
        if 80 <= index < 90:
            close -= 0.6
        elif index == 90:
            close += 6.0
        elif 91 <= index < 105:
            close += 0.9
        elif 105 <= index < 118:
            close -= 1.4
        else:
            close += 0.18

        open_price = close - 0.4
        volume = 5000 if 90 <= index < 95 else 1800
        bars.append(
            PriceBar(
                symbol="AKBNK",
                timestamp=start + timedelta(days=index),
                open=open_price,
                high=close + 0.8,
                low=open_price - 0.7,
                close=close,
                volume=volume,
                timeframe="1d",
            )
        )
    return bars


def test_real_research_breakout_strategy_generates_trade_records() -> None:
    bars = build_breakout_bars()
    indicators = compute_indicators(bars)

    trades = simulate_strategy(
        strategy_id="cluster:breakout",
        symbol="AKBNK",
        family=StrategyFamily.BREAKOUT_VOLUME,
        bars=bars,
        indicators=indicators,
    )

    assert len(trades) >= 1
    assert trades[0].entry_price is not None
    assert trades[0].exit_price is not None
    assert trades[0].entered_at < trades[0].exited_at
