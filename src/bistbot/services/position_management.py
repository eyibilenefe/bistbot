from __future__ import annotations

from datetime import datetime


def should_keep_position_open(
    *,
    opened_at: datetime,
    as_of: datetime,
    daily_close: float,
    daily_ema20: float,
    daily_ema50: float,
    soft_limit_days: int = 7,
) -> bool:
    holding_days = (as_of.date() - opened_at.date()).days
    if holding_days <= soft_limit_days:
        return True
    return daily_close > daily_ema20 and daily_ema20 > daily_ema50
