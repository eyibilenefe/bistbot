from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(slots=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    test_start: date
    test_end: date


def generate_walk_forward_windows(
    *,
    end_date: date,
    lookback_days: int = 720,
    train_days: int = 60,
    test_days: int = 30,
    step_days: int = 30,
) -> list[WalkForwardWindow]:
    earliest_start = end_date - timedelta(days=lookback_days)
    windows: list[WalkForwardWindow] = []
    current_train_start = earliest_start

    while True:
        train_end = current_train_start + timedelta(days=train_days - 1)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_days - 1)
        if test_end > end_date:
            break
        windows.append(
            WalkForwardWindow(
                train_start=current_train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        current_train_start += timedelta(days=step_days)

    return windows
