from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from bistbot.domain.enums import (
    ClusterFallbackMode,
    CorporateActionType,
    DataQualityEventType,
    LifecycleEventType,
    PositionStatus,
    SetupStatus,
    StrategyFamily,
)


@dataclass(slots=True)
class PriceBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str


@dataclass(slots=True)
class SymbolSnapshot:
    symbol: str
    sector: str
    atr_percent_60d: float
    as_of: date
    tradeable: bool = True


@dataclass(slots=True)
class ClusterDefinition:
    id: str
    sector: str
    vol_bucket: str
    symbol_count: int
    fallback_mode: ClusterFallbackMode
    as_of: date
    members: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StrategyDefinition:
    id: str
    name: str
    family: StrategyFamily
    trend_indicator: str
    momentum_indicator: str
    volume_indicator: str
    params: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True


@dataclass(slots=True)
class StrategyScore:
    strategy_id: str
    cluster_id: str
    as_of: date
    family: StrategyFamily
    total_return: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    trade_count: int
    avg_trade_return: float
    estimated_round_trip_cost: float
    oos_window_trade_counts: list[int] = field(default_factory=list)
    oos_returns: list[float] = field(default_factory=list)
    walk_forward_window_count: int = 0
    backtest_mode: str = "walk_forward"
    normalized_return: float = 0.0
    normalized_win_rate: float = 0.0
    normalized_profit_factor: float = 0.0
    normalized_max_drawdown: float = 0.0
    composite_score: float = 0.0


@dataclass(slots=True)
class SetupCandidate:
    id: str
    symbol: str
    cluster_id: str
    strategy_id: str
    strategy_family: StrategyFamily
    score: float
    entry_low: float
    entry_high: float
    stop: float
    target: float
    confidence: float
    confluence_score: float
    expected_r: float
    created_at: datetime
    expires_at: datetime
    wf_window_count: int = 0
    wf_win_rate: float = 0.0
    wf_total_return_pct: float = 0.0
    thesis: str = ""
    status: SetupStatus = SetupStatus.ACTIVE
    invalidated_reason: str | None = None


@dataclass(slots=True)
class PortfolioPosition:
    id: str
    symbol: str
    sector: str
    status: PositionStatus
    entry_price: float
    stop_price: float
    target_price: float
    quantity: int
    last_price: float
    opened_at: datetime
    entry_reason: str = ""
    success_probability: float | None = None
    closed_at: datetime | None = None
    adjustment_factor: float = 1.0
    adjusted_entry_price: float | None = None
    adjusted_stop_price: float | None = None
    adjusted_target_price: float | None = None
    last_corporate_action_at: datetime | None = None
    source_setup_id: str | None = None
    initial_stop_price: float | None = None
    initial_target_price: float | None = None
    expected_r_at_entry: float | None = None
    confidence_at_entry: float | None = None


@dataclass(slots=True)
class ProposedPosition:
    symbol: str
    sector: str
    entry_price: float
    stop_price: float
    last_price: float
    quantity: int


@dataclass(slots=True)
class CorporateAction:
    symbol: str
    action_type: CorporateActionType
    effective_at: datetime
    factor: float = 1.0
    cash_amount: float = 0.0
    reference: str | None = None


@dataclass(slots=True)
class DataQualityEvent:
    symbol: str
    event_type: DataQualityEventType
    detected_at: datetime
    corporate_action_ref: str | None
    resolution: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradeRecord:
    strategy_id: str
    symbol: str
    entered_at: datetime
    exited_at: datetime
    return_pct: float
    r_multiple: float
    entry_price: float | None = None
    exit_price: float | None = None


@dataclass(slots=True)
class JobRun:
    name: str
    started_at: datetime
    completed_at: datetime
    status: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LifecycleEvent:
    id: str
    event_type: LifecycleEventType
    occurred_at: datetime
    symbol: str | None = None
    setup_id: str | None = None
    position_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DashboardOverview:
    total_value: float
    simulated_return_pct: float
    active_ideas: int
    open_positions: int
