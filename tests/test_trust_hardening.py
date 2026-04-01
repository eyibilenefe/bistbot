from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import nan

from fastapi.testclient import TestClient

from bistbot.config import get_settings
from bistbot.domain.enums import PositionStatus
from bistbot.domain.models import PortfolioPosition, PriceBar
from bistbot.main import create_app
from bistbot.providers.base import MarketDataProvider
from bistbot.storage.memory import InMemoryStore


class StableMarketDataProvider(MarketDataProvider):
    def fetch_symbols(self) -> list[str]:
        return ["AKBNK", "KCHOL", "TUPRS", "YKBNK"]

    def fetch_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        force_refresh: bool = False,
    ) -> list[PriceBar]:
        delta = timedelta(hours=1) if timeframe == "1h" else timedelta(days=1)
        bars: list[PriceBar] = []
        current = start if start.tzinfo else start.replace(tzinfo=UTC)
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        price = 210.0 if symbol == "KCHOL" else 100.0 + (len(symbol) * 2)
        while current <= end and len(bars) < 40:
            close = price + 0.4
            bars.append(
                PriceBar(
                    symbol=symbol,
                    timestamp=current,
                    open=price,
                    high=close + 0.6,
                    low=price - 0.5,
                    close=close,
                    volume=10_000,
                    timeframe=timeframe,
                )
            )
            current += delta
            price += 0.3
        return bars

    def fetch_sectors(self, *, as_of, progress_callback=None):
        return {"AKBNK": "banking", "KCHOL": "holding", "TUPRS": "energy", "YKBNK": "banking"}

    def fetch_corporate_actions(self, *, start=None, end=None):
        return []

    def run_data_quality_check(self):
        return []


class NaNMarketDataProvider(StableMarketDataProvider):
    def fetch_symbols(self) -> list[str]:
        return ["AKBNK"]

    def fetch_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        force_refresh: bool = False,
    ) -> list[PriceBar]:
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        if timeframe == "1h" and symbol == "KCHOL":
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
        return [
            PriceBar(
                symbol=symbol,
                timestamp=start,
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.0,
                volume=1_000,
                timeframe=timeframe,
            ),
            PriceBar(
                symbol=symbol,
                timestamp=end,
                open=10.0,
                high=11.0,
                low=9.0,
                close=nan,
                volume=1_000,
                timeframe=timeframe,
            ),
        ]


def build_client(provider: MarketDataProvider | None = None) -> TestClient:
    app = create_app(
        market_data_provider=provider or StableMarketDataProvider(),
        seed_demo_data=True,
    )
    app.state.store.settings.auto_paper_trading_enabled = False
    return TestClient(app)


def test_position_reason_is_consistent_across_position_view_dashboard_and_chart() -> None:
    settings = get_settings()
    settings.auto_paper_trading_enabled = False
    store = InMemoryStore(
        settings,
        market_data_provider=StableMarketDataProvider(),
        seed_demo_data=True,
    )

    store.update_position("pos-1", stop_price=205.0)

    position_view = store.get_position_view("pos-1")
    dashboard_position = store.get_dashboard_page_data()["positions"][0]
    chart = store.get_live_trade_charts()[0]

    assert position_view is not None
    assert position_view["stop_price"] == 205.0
    assert "205.00 stop" in str(position_view["entry_reason"])
    assert dashboard_position["entry_reason"] == position_view["entry_reason"]
    assert chart["entry_reason"] == position_view["entry_reason"]


def test_nan_market_data_is_hidden_on_dashboard_and_kept_as_degraded_api_payload() -> None:
    client = build_client(NaNMarketDataProvider())

    chart_response = client.get("/api/market/charts/AKBNK")
    assert chart_response.status_code == 200
    chart_payload = chart_response.json()
    assert chart_payload["is_degraded"] is True
    assert chart_payload["filtered_candle_count"] == 1
    assert chart_payload["candles"]

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert "1 satir gecersiz veri nedeniyle gizlendi." in dashboard_response.text
    assert ">nan<" not in dashboard_response.text.lower()


def test_positions_api_keeps_degraded_item_but_dashboard_hides_it() -> None:
    client = build_client()
    app = client.app
    app.state.store.positions["pos-1"].stop_price = nan
    app.state.store.positions["pos-1"].adjusted_stop_price = nan

    positions_response = client.get("/api/positions")
    assert positions_response.status_code == 200
    degraded_position = positions_response.json()[0]
    assert degraded_position["is_degraded"] is True
    assert "stop_price_invalid" in degraded_position["degraded_reasons"]
    assert degraded_position["stop_price"] is None

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert "1 pozisyon gecersiz veri nedeniyle tabloda gizlendi." in dashboard_response.text


def test_manual_entry_response_persists_entry_context_fields() -> None:
    client = build_client()

    top_setup = client.get("/api/setups/top").json()[0]
    approve_response = client.post(f"/api/setups/{top_setup['id']}/approve")
    assert approve_response.status_code == 200

    entry_response = client.post(
        "/api/positions/manual-entry",
        json={"setup_id": top_setup["id"], "fill_price": top_setup["entry_high"]},
    )
    assert entry_response.status_code == 200
    payload = entry_response.json()
    assert payload["source_setup_id"] == top_setup["id"]
    assert payload["expected_r_at_entry"] == top_setup["expected_r"]
    assert payload["confidence_at_entry"] == top_setup["confidence"]
    assert payload["success_probability"] == top_setup["confidence"]
    assert payload["is_degraded"] is False


def test_invalid_long_values_are_rejected_for_manual_entry_and_position_update() -> None:
    client = build_client()
    top_setup = client.get("/api/setups/top").json()[0]
    client.post(f"/api/setups/{top_setup['id']}/approve")

    invalid_entry_response = client.post(
        "/api/positions/manual-entry",
        json={"setup_id": top_setup["id"], "fill_price": top_setup["stop"]},
    )
    assert invalid_entry_response.status_code == 400
    assert "Entry price must be above stop price" in invalid_entry_response.json()["detail"]

    invalid_update_response = client.patch(
        "/api/positions/pos-1",
        json={"target_price": 200.0},
    )
    assert invalid_update_response.status_code == 400
    assert "Target price must be above entry price" in invalid_update_response.json()["detail"]


def test_trailing_stop_uses_initial_risk_for_breakeven_and_plus_1r_moves() -> None:
    settings = get_settings()
    settings.auto_paper_trading_enabled = False
    store = InMemoryStore(settings, seed_demo_data=True)
    store.lifecycle_events = []
    store._event_sequence = 0
    first_bar_time = datetime(2026, 3, 26, 10, tzinfo=UTC)
    second_bar_time = datetime(2026, 3, 26, 14, tzinfo=UTC)
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
            initial_stop_price=19.0,
            initial_target_price=24.0,
        )
    }
    store.bars_by_symbol = {
        "AKBNK": [
            PriceBar(
                symbol="AKBNK",
                timestamp=first_bar_time,
                open=20.2,
                high=21.1,
                low=20.4,
                close=21.0,
                volume=25_000,
                timeframe="4h",
            )
        ]
    }

    store._refresh_open_positions(now=first_bar_time)
    assert store.positions["pos-1"].stop_price == 20.0

    store.bars_by_symbol["AKBNK"] = [
        PriceBar(
            symbol="AKBNK",
            timestamp=second_bar_time,
            open=21.0,
            high=22.2,
            low=21.5,
            close=22.0,
            volume=26_000,
            timeframe="4h",
        )
    ]

    store._refresh_open_positions(now=second_bar_time)

    assert store.positions["pos-1"].stop_price == 21.0
    event_types = [item["event_type"] for item in store.get_lifecycle_events(limit=5)]
    assert "stop_moved_to_plus_1r" in event_types
    assert "stop_moved_to_breakeven" in event_types


def test_lifecycle_events_are_exposed_via_api() -> None:
    client = build_client()
    top_setup = client.get("/api/setups/top").json()[0]

    approve_response = client.post(f"/api/setups/{top_setup['id']}/approve")
    assert approve_response.status_code == 200
    entry_response = client.post(
        "/api/positions/manual-entry",
        json={"setup_id": top_setup["id"], "fill_price": top_setup["entry_high"]},
    )
    assert entry_response.status_code == 200

    events_response = client.get("/api/events/lifecycle?limit=20")
    assert events_response.status_code == 200
    event_types = [item["event_type"] for item in events_response.json()]
    assert "setup_approved" in event_types
    assert "position_entered" in event_types
