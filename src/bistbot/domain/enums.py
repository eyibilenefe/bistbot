from __future__ import annotations

from enum import StrEnum


class StrategyFamily(StrEnum):
    TREND_FOLLOWING = "trend_following"
    PULLBACK_MEAN_REVERSION = "pullback_mean_reversion"
    BREAKOUT_VOLUME = "breakout_volume"


class SetupStatus(StrEnum):
    ACTIVE = "active"
    APPROVED_PENDING_ENTRY = "approved_pending_entry"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    ENTERED = "entered"
    CLOSED = "closed"


class ClusterFallbackMode(StrEnum):
    NONE = "none"
    ADJACENT_VOLATILITY_MERGE = "adjacent_volatility_merge"
    SECTOR_ONLY = "sector_only"


class CorporateActionType(StrEnum):
    SPLIT = "split"
    BONUS = "bonus"
    CASH_DIVIDEND = "cash_dividend"


class PositionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class DataQualityEventType(StrEnum):
    UNEXPLAINED_GAP = "unexplained_gap"
    STALE_DATA = "stale_data"


class JobName(StrEnum):
    SYNC_DAILY_DATA = "sync_daily_data"
    SYNC_HOURLY_DATA = "sync_hourly_data"
    COMPUTE_INDICATORS = "compute_indicators"
    RUN_BACKTESTS = "run_backtests"
    SCORE_STRATEGIES = "score_strategies"
    SCAN_SETUPS = "scan_setups"
    REFRESH_PORTFOLIO = "refresh_portfolio"
