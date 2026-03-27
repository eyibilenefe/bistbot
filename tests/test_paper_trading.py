from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bistbot.config import get_settings
from bistbot.domain.enums import PositionStatus, SetupStatus
from bistbot.domain.models import PortfolioPosition, PriceBar
from bistbot.providers.base import MarketDataProvider
from bistbot.storage.memory import InMemoryStore


class LiveRefreshProvider(MarketDataProvider):
    def __init__(self) -> None:
        self.force_refresh_calls: list[bool] = []

    def fetch_symbols(self) -> list[str]:
        return ["KCHOL"]

    def fetch_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        force_refresh: bool = False,
    ) -> list[PriceBar]:
        self.force_refresh_calls.append(force_refresh)
        if timeframe == "1d":
            return []
        return [
            PriceBar(
                symbol=symbol,
                timestamp=end,
                open=219.0,
                high=221.0,
                low=218.5,
                close=220.5,
                volume=30_000,
                timeframe=timeframe,
            )
        ]

    def fetch_sectors(self, *, as_of, progress_callback=None):
        return {"KCHOL": "holding"}

    def fetch_corporate_actions(self, *, start=None, end=None):
        return []

    def run_data_quality_check(self):
        return []


def test_auto_paper_trading_opens_position_from_active_setup() -> None:
    settings = get_settings()
    store = InMemoryStore(settings, seed_demo_data=True)
    store.positions = {}
    store.cash_balance = settings.initial_portfolio_cash

    setup = next(iter(store.setups.values()))
    fill_price = round((setup.entry_low + setup.entry_high) / 2, 2)
    bar_time = datetime(2026, 3, 26, 10, tzinfo=UTC)
    store.bars_by_symbol = {
        setup.symbol: [
            PriceBar(
                symbol=setup.symbol,
                timestamp=bar_time,
                open=fill_price - 0.2,
                high=fill_price + 0.3,
                low=fill_price - 0.4,
                close=fill_price,
                volume=20_000,
                timeframe="4h",
            )
        ]
    }

    opened = store._auto_enter_setups(now=bar_time)

    assert opened == 1
    assert len(store.positions) == 1
    position = next(iter(store.positions.values()))
    assert position.status == PositionStatus.OPEN
    assert position.symbol == setup.symbol
    assert position.entry_reason
    assert position.success_probability == setup.confidence
    assert store.setups[setup.id].status == SetupStatus.ENTERED
    assert store.setups[setup.id].thesis


def test_auto_paper_trading_closes_position_when_stop_is_hit() -> None:
    settings = get_settings()
    store = InMemoryStore(settings, seed_demo_data=True)
    store.positions = {
        "pos-1": PortfolioPosition(
            id="pos-1",
            symbol="AKBNK",
            sector="banking",
            status=PositionStatus.OPEN,
            entry_price=20.0,
            stop_price=19.0,
            target_price=24.0,
            quantity=100,
            last_price=20.0,
            opened_at=datetime(2026, 3, 24, tzinfo=UTC),
            adjusted_entry_price=20.0,
            adjusted_stop_price=19.0,
            adjusted_target_price=24.0,
        )
    }
    store.cash_balance = 1_000.0
    bar_time = datetime(2026, 3, 26, 14, tzinfo=UTC)
    store.bars_by_symbol = {
        "AKBNK": [
            PriceBar(
                symbol="AKBNK",
                timestamp=bar_time,
                open=19.8,
                high=20.2,
                low=18.7,
                close=19.1,
                volume=25_000,
                timeframe="4h",
            )
        ]
    }

    closed = store._refresh_open_positions(now=bar_time)

    assert closed == 1
    position = store.positions["pos-1"]
    assert position.status == PositionStatus.CLOSED
    assert position.closed_at == bar_time
    assert position.last_price == 19.0
    assert store.cash_balance == 2_900.0


def test_open_positions_are_refreshed_with_fresh_market_data() -> None:
    settings = get_settings()
    provider = LiveRefreshProvider()
    store = InMemoryStore(
        settings,
        market_data_provider=provider,
        seed_demo_data=True,
    )

    overview = store.get_dashboard_overview()

    assert overview.open_positions == 1
    position = store.positions["pos-1"]
    assert position.last_price == 220.5
    assert any(provider.force_refresh_calls)
