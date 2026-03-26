from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from bistbot.domain.enums import DataQualityEventType
from bistbot.domain.models import CorporateAction, DataQualityEvent, PriceBar


def run_data_quality_check(
    bars: list[PriceBar],
    corporate_actions: list[CorporateAction],
    *,
    unexplained_gap_threshold: float = 0.18,
) -> list[DataQualityEvent]:
    events: list[DataQualityEvent] = []
    actions_by_symbol_and_day: dict[tuple[str, datetime.date], list[CorporateAction]] = defaultdict(list)
    for action in corporate_actions:
        actions_by_symbol_and_day[(action.symbol, action.effective_at.date())].append(action)

    grouped_bars: dict[str, list[PriceBar]] = defaultdict(list)
    for bar in bars:
        grouped_bars[bar.symbol].append(bar)

    for symbol, symbol_bars in grouped_bars.items():
        ordered = sorted(symbol_bars, key=lambda bar: bar.timestamp)
        for previous_bar, current_bar in zip(ordered, ordered[1:]):
            if previous_bar.close <= 0:
                continue
            gap = abs(current_bar.open - previous_bar.close) / previous_bar.close
            if gap <= unexplained_gap_threshold:
                continue
            actions = actions_by_symbol_and_day.get((symbol, current_bar.timestamp.date()), [])
            if actions:
                continue
            events.append(
                DataQualityEvent(
                    symbol=symbol,
                    event_type=DataQualityEventType.UNEXPLAINED_GAP,
                    detected_at=current_bar.timestamp,
                    corporate_action_ref=None,
                    resolution="quarantined",
                    details={"gap": gap},
                )
            )
    return events
