from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bistbot.domain.models import PriceBar
from bistbot.services.charting import (
    build_candlestick_chart,
    build_demo_bars_from_anchors,
    build_price_line,
    build_price_marker,
)


def test_candlestick_chart_payload_contains_ohlc_and_markers() -> None:
    start = datetime(2026, 3, 20, tzinfo=UTC)
    bars = [
        PriceBar(
            symbol="AKBNK",
            timestamp=start + timedelta(hours=index),
            open=10 + index,
            high=10.8 + index,
            low=9.7 + index,
            close=10.4 + index,
            volume=1000 + index,
            timeframe="1h",
        )
        for index in range(4)
    ]
    payload = build_candlestick_chart(
        symbol="AKBNK",
        title="AKBNK Live Trade",
        subtitle="Real candles",
        bars=bars,
        markers=[
            build_price_marker(
                timestamp=bars[0].timestamp,
                text="Entry 10.00",
                color="#0d8a76",
                shape="arrowUp",
                position="belowBar",
            )
        ],
        price_lines=[
            build_price_line(value=9.5, title="Stop 9.50", color="#b33c2b")
        ],
    )

    assert len(payload["candles"]) == 4
    assert payload["candles"][0]["open"] == 10
    assert payload["markers"][0]["text"] == "Entry 10.00"
    assert payload["price_lines"][0]["price"] == 9.5


def test_demo_bars_fallback_builds_ohlc_series() -> None:
    bars = build_demo_bars_from_anchors(
        symbol="AKBNK",
        timeframe="1d",
        anchors=[(0, 10.0), (5, 11.0), (9, 10.4)],
        points=10,
        end=datetime(2026, 3, 25, tzinfo=UTC),
    )

    assert len(bars) == 10
    assert bars[0].timeframe == "1d"
    assert bars[-1].close > 0
