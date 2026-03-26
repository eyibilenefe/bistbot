from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from bistbot.domain.models import PriceBar


def build_candlestick_chart(
    *,
    symbol: str,
    title: str,
    subtitle: str,
    bars: list[PriceBar],
    markers: list[dict[str, object]] | None = None,
    price_lines: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    markers = markers or []
    price_lines = price_lines or []

    candles = [
        {
            "time": int(_ensure_utc(bar.timestamp).timestamp()),
            "open": round(bar.open, 4),
            "high": round(bar.high, 4),
            "low": round(bar.low, 4),
            "close": round(bar.close, 4),
        }
        for bar in bars
    ]
    return {
        "symbol": symbol,
        "title": title,
        "subtitle": subtitle,
        "candles": candles,
        "markers": markers,
        "price_lines": price_lines,
        "last_price": candles[-1]["close"] if candles else None,
        "start_label": _format_label(bars[0].timestamp) if bars else None,
        "end_label": _format_label(bars[-1].timestamp) if bars else None,
    }


def build_price_marker(
    *,
    timestamp: datetime,
    text: str,
    color: str,
    shape: str,
    position: str,
) -> dict[str, object]:
    return {
        "time": int(_ensure_utc(timestamp).timestamp()),
        "position": position,
        "color": color,
        "shape": shape,
        "text": text,
    }


def build_price_line(
    *,
    value: float,
    title: str,
    color: str,
) -> dict[str, object]:
    return {
        "price": round(value, 4),
        "title": title,
        "color": color,
        "lineWidth": 2,
    }


def build_demo_bars_from_anchors(
    *,
    symbol: str,
    timeframe: str,
    anchors: list[tuple[int, float]],
    points: int,
    end: datetime,
) -> list[PriceBar]:
    closes = _synthetic_closes(symbol=symbol, anchors=anchors, points=points)
    bars: list[PriceBar] = []
    delta = timedelta(hours=1) if timeframe == "1h" else timedelta(days=1)

    previous_close = closes[0]
    for index, close in enumerate(closes):
        timestamp = end - delta * (points - 1 - index)
        open_price = previous_close
        wick_seed = abs(math.sin((index + len(symbol)) / 3.1))
        body_high = max(open_price, close)
        body_low = min(open_price, close)
        high = body_high + max(close * 0.008 * (0.4 + wick_seed), 0.05)
        low = max(body_low - max(close * 0.008 * (0.35 + wick_seed), 0.05), 0.01)
        bars.append(
            PriceBar(
                symbol=symbol,
                timestamp=_ensure_utc(timestamp),
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close, 4),
                volume=1000 + (index * 37),
                timeframe=timeframe,
            )
        )
        previous_close = close
    return bars


def _synthetic_closes(
    *,
    symbol: str,
    anchors: list[tuple[int, float]],
    points: int,
) -> list[float]:
    if points < 2:
        raise ValueError("points must be at least 2")

    sorted_anchors = sorted(anchors, key=lambda item: item[0])
    if sorted_anchors[0][0] != 0:
        sorted_anchors.insert(0, (0, sorted_anchors[0][1]))
    if sorted_anchors[-1][0] != points - 1:
        sorted_anchors.append((points - 1, sorted_anchors[-1][1]))

    seed = sum(ord(char) for char in symbol)
    base_reference = sum(value for _, value in sorted_anchors) / len(sorted_anchors)
    closes: list[float] = []

    for index in range(points):
        left_anchor, right_anchor = _surrounding_anchors(sorted_anchors, index)
        if left_anchor[0] == right_anchor[0]:
            base_value = left_anchor[1]
        else:
            progress = (index - left_anchor[0]) / (right_anchor[0] - left_anchor[0])
            base_value = left_anchor[1] + (right_anchor[1] - left_anchor[1]) * progress

        noise = (
            math.sin((index + seed % 7) / 2.5) * base_reference * 0.018
            + math.cos((index + seed % 13) / 4.0) * base_reference * 0.009
        )
        closes.append(round(max(base_value + noise, 0.01), 4))

    for anchor_index, anchor_value in sorted_anchors:
        closes[anchor_index] = round(anchor_value, 4)

    return closes


def _surrounding_anchors(
    anchors: list[tuple[int, float]], index: int
) -> tuple[tuple[int, float], tuple[int, float]]:
    left = anchors[0]
    right = anchors[-1]
    for anchor in anchors:
        if anchor[0] <= index:
            left = anchor
        if anchor[0] >= index:
            right = anchor
            break
    return left, right


def _ensure_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _format_label(timestamp: datetime) -> str:
    timestamp = _ensure_utc(timestamp)
    return timestamp.strftime("%Y-%m-%d %H:%M")
