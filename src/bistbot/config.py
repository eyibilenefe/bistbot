from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    initial_portfolio_cash: float = 30_000.0
    risk_per_trade: float = 0.01
    auto_paper_trading_enabled: bool = True
    auto_paper_max_new_positions_per_refresh: int = 5
    paper_trade_soft_limit_days: int = 7
    live_position_refresh_interval_seconds: int = 120
    max_sector_positions: int = 2
    max_sector_exposure: float = 0.40
    max_correlation: float = 0.75
    max_total_portfolio_risk: float = 0.05
    min_cluster_size: int = 8
    setup_expiration_hours: int = 6
    quality_gate_percentile: float = 0.20
    quality_gate_min_keep: int = 3
    setup_signal_lookback_bars: int = 6
    setup_min_expected_r: float = 1.5
    setup_min_confluence_score: float = 0.65
    research_timeframe: str = "4h"
    backtest_lookback_days: int = 730
    backtest_min_daily_bars: int = 240
    backtest_symbol_summary_limit: int = 0
    backtest_trade_chart_limit: int = 24
    chart_live_lookback_days: int = 10
    chart_backtest_padding_days: int = 20
    market_chart_lookback_days: int = 730
    enable_real_market_data: bool = True
    cache_dir: str = ".cache/bistbot"
    persist_runtime_state: bool = True


def get_settings() -> Settings:
    return Settings()
