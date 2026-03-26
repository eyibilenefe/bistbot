from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol

from bistbot.domain.models import (
    ClusterDefinition,
    CorporateAction,
    DashboardOverview,
    PortfolioPosition,
    SetupCandidate,
    StrategyScore,
    TradeRecord,
)


class StorageRepository(Protocol):
    def get_dashboard_overview(self) -> DashboardOverview: ...

    def list_top_setups(self, *, limit: int = 3) -> list[SetupCandidate]: ...

    def get_setup(self, setup_id: str) -> SetupCandidate | None: ...

    def approve_setup(self, setup_id: str) -> SetupCandidate: ...

    def reject_setup(self, setup_id: str) -> SetupCandidate: ...

    def create_manual_position(
        self,
        *,
        setup_id: str,
        fill_price: float,
        filled_at: datetime,
        quantity: int | None,
    ) -> PortfolioPosition: ...

    def update_position(
        self,
        position_id: str,
        *,
        stop_price: float | None = None,
        target_price: float | None = None,
        last_price: float | None = None,
        status: str | None = None,
        closed_at: datetime | None = None,
    ) -> PortfolioPosition: ...

    def get_position(self, position_id: str) -> PortfolioPosition | None: ...

    def list_positions(self) -> list[PortfolioPosition]: ...

    def list_backtest_clusters(self) -> list[dict[str, object]]: ...

    def list_cluster_strategies(self, cluster_id: str) -> list[StrategyScore]: ...

    def list_strategy_trades(self, strategy_id: str) -> list[TradeRecord]: ...

    def apply_corporate_action(self, action: CorporateAction) -> float: ...

    def get_strategy_insights(self, *, limit: int = 3) -> dict[str, list[dict[str, object]]]: ...

    def get_dashboard_page_data(self) -> dict[str, object]: ...

    def get_backtest_page_data(self) -> dict[str, object]: ...

    def get_live_trade_charts(self) -> list[dict[str, object]]: ...

    def get_backtest_trade_charts(self, *, limit: int = 3) -> list[dict[str, object]]: ...

    def list_available_symbols(self) -> list[str]: ...

    def get_market_symbol_chart(
        self,
        symbol: str,
        *,
        lookback_days: int | None = None,
    ) -> dict[str, object] | None: ...

    def list_backtest_symbols(self, *, limit: int | None = None) -> list[dict[str, object]]: ...

    def get_backtest_symbol_chart(self, symbol: str) -> dict[str, object] | None: ...

    def refresh_research_data(
        self,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict[str, object]: ...
