from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from bistbot.domain.enums import StrategyFamily
from bistbot.domain.models import PriceBar
from bistbot.domain.models import StrategyDefinition, StrategyScore, TradeRecord
from bistbot.main import create_app
from bistbot.providers.base import MarketDataProvider


class FakeMarketDataProvider(MarketDataProvider):
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
        if timeframe == "1h":
            delta = timedelta(hours=1)
        elif timeframe == "4h":
            delta = timedelta(hours=4)
        else:
            delta = timedelta(days=1)
        bars: list[PriceBar] = []
        current = start
        price = 210.0 if symbol == "KCHOL" else 100.0 + (len(symbol) * 2)
        while current <= end and len(bars) < 40:
            close = price + 0.4
            bars.append(
                PriceBar(
                    symbol=symbol,
                    timestamp=current if current.tzinfo else current.replace(tzinfo=UTC),
                    open=price,
                    high=close + 0.6,
                    low=price - 0.5,
                    close=close,
                    volume=10000,
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


def build_client() -> TestClient:
    app = create_app(
        market_data_provider=FakeMarketDataProvider(),
        seed_demo_data=True,
    )
    return TestClient(app)


def test_dashboard_and_manual_entry_flow() -> None:
    client = build_client()

    overview_response = client.get("/api/dashboard/overview")
    assert overview_response.status_code == 200
    assert "active_ideas" in overview_response.json()

    setups_response = client.get("/api/setups/top")
    assert setups_response.status_code == 200
    top_setups = setups_response.json()
    assert len(top_setups) >= 1
    assert top_setups[0]["wf_window_count"] >= 1

    setup_id = top_setups[0]["id"]
    approve_response = client.post(f"/api/setups/{setup_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved_pending_entry"

    entry_response = client.post(
        "/api/positions/manual-entry",
        json={"setup_id": setup_id, "fill_price": 21.2},
    )
    assert entry_response.status_code == 200
    assert entry_response.json()["symbol"] == top_setups[0]["symbol"]
    assert entry_response.json()["success_probability"] == top_setups[0]["confidence"]
    position_id = entry_response.json()["id"]

    close_response = client.patch(
        f"/api/positions/{position_id}",
        json={"last_price": 22.4, "status": "closed"},
    )
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "closed"

    clusters_response = client.get("/api/backtests/clusters")
    assert clusters_response.status_code == 200
    assert len(clusters_response.json()) >= 1
    assert clusters_response.json()[0]["backtest_mode"] == "walk_forward"

    market_chart_response = client.get("/api/market/charts/AKBNK")
    assert market_chart_response.status_code == 200
    assert len(market_chart_response.json()["candles"]) >= 1

    backtest_symbols_response = client.get("/api/backtests/symbols")
    assert backtest_symbols_response.status_code == 200
    assert len(backtest_symbols_response.json()) >= 1
    assert backtest_symbols_response.json()[0]["backtest_mode"] == "walk_forward"

    backtest_symbol_chart_response = client.get("/api/backtests/symbols/AKBNK")
    assert backtest_symbol_chart_response.status_code == 200
    assert len(backtest_symbol_chart_response.json()["candles"]) >= 1
    assert backtest_symbol_chart_response.json()["backtest_mode"] == "walk_forward"

    paper_trade_history_response = client.get("/api/paper-trades/history")
    assert paper_trade_history_response.status_code == 200
    assert any(item["id"] == position_id for item in paper_trade_history_response.json())

    paper_trade_chart_response = client.get(f"/api/paper-trades/symbols/{top_setups[0]['symbol']}")
    assert paper_trade_chart_response.status_code == 200
    assert len(paper_trade_chart_response.json()["candles"]) >= 1
    assert paper_trade_chart_response.json()["paper_trade_count"] >= 1


def test_html_dashboard_and_backtest_pages_render() -> None:
    client = build_client()

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert "Yuksek Guvenli Kurulumlar" in dashboard_response.text
    assert "BISTBot" in dashboard_response.text
    assert "Canli Islem Haritasi" in dashboard_response.text
    assert "Tum Hisseler" in dashboard_response.text
    assert "Grafik Yukle" in dashboard_response.text
    assert "Giris" in dashboard_response.text
    assert "Basari Olasiligi" in dashboard_response.text
    assert "WF Pencere" in dashboard_response.text
    assert "Yahoo Finance (.IS)" in dashboard_response.text
    assert "Neden Secildi" in dashboard_response.text
    assert "Giris Gerekcesi" in dashboard_response.text
    assert "Gecmis islemler" in dashboard_response.text
    assert "Paper Trade Haritasi" in dashboard_response.text
    assert "Paper Trade Yukle" in dashboard_response.text

    backtest_response = client.get("/backtest")
    assert backtest_response.status_code == 200
    assert "Gercek veri kume siralamasi" in backtest_response.text
    assert "En Basarili Hisseler" in backtest_response.text
    assert "Istedigin hissenin backtestini ac" in backtest_response.text
    assert "Walk-forward OOS" in backtest_response.text
    assert "Tarihsel Trade Isaretleri" in backtest_response.text
    assert (
        "Cikis" in backtest_response.text
        or "Gercek trade ureten 2 yillik backtest sonucuna henuz ulasilamadi." in backtest_response.text
    )


def test_refresh_job_endpoints_return_progress_payload() -> None:
    client = build_client()

    refresh_response = client.post("/api/cache/refresh")
    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert "job_id" in payload
    assert "progress" in payload

    status_response = client.get(f"/api/cache/refresh/{payload['job_id']}")
    assert status_response.status_code == 200
    assert "status" in status_response.json()
    assert "progress" in status_response.json()


def test_over_30pct_maxdd_strategies_are_hidden_from_backtest_views() -> None:
    app = create_app(
        market_data_provider=FakeMarketDataProvider(),
        seed_demo_data=True,
    )
    store = app.state.store
    store.strategies["junk-strategy"] = StrategyDefinition(
        id="junk-strategy",
        name="Cop Strateji",
        family=StrategyFamily.TREND_FOLLOWING,
        trend_indicator="EMA20/50",
        momentum_indicator="MACD",
        volume_indicator="OBV",
    )
    store.strategy_scores["junk-strategy"] = StrategyScore(
        strategy_id="junk-strategy",
        cluster_id="banking:low",
        as_of=date(2026, 3, 26),
        family=StrategyFamily.TREND_FOLLOWING,
        total_return=0.90,
        win_rate=0.95,
        profit_factor=4.20,
        max_drawdown=0.31,
        trade_count=200,
        avg_trade_return=0.03,
        estimated_round_trip_cost=0.002,
        oos_window_trade_counts=[5, 5, 5, 5, 5, 5],
        oos_returns=[0.05, 0.03, 0.04, 0.02, 0.03, 0.05],
        composite_score=float("-inf"),
    )
    store.backtest_trades["junk-strategy"] = [
        TradeRecord(
            strategy_id="junk-strategy",
            symbol="ZZZZ",
            entered_at=datetime(2026, 1, 2, tzinfo=UTC),
            exited_at=datetime(2026, 1, 8, tzinfo=UTC),
            return_pct=0.12,
            r_multiple=2.1,
            entry_price=10.0,
            exit_price=11.2,
        )
    ]

    client = TestClient(app)

    strategies_response = client.get("/api/backtests/clusters/banking:low/strategies")
    assert strategies_response.status_code == 200
    assert all(item["strategy_id"] != "junk-strategy" for item in strategies_response.json())

    symbols_response = client.get("/api/backtests/symbols")
    assert symbols_response.status_code == 200
    assert all(item["symbol"] != "ZZZZ" for item in symbols_response.json())
