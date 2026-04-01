from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from bistbot.config import Settings
from bistbot.domain.models import PriceBar
from bistbot.providers.base import MarketDataProvider
from bistbot.services.backtest import generate_walk_forward_windows
from bistbot.services.research import build_real_research_state
from bistbot.storage.memory import InMemoryStore


class WalkForwardProvider(MarketDataProvider):
    def fetch_symbols(self) -> list[str]:
        return ["AKBNK", "YKBNK"]

    def fetch_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        force_refresh: bool = False,
    ) -> list[PriceBar]:
        bars: list[PriceBar] = []
        current = start
        close = 100.0 + (5.0 if symbol == "YKBNK" else 0.0)
        for index in range(320):
            if 70 <= index % 120 <= 75:
                close += 5.0
            elif 76 <= index % 120 <= 95:
                close += 0.8
            elif 96 <= index % 120 <= 104:
                close -= 0.4
            else:
                close += 0.12
            bars.append(
                PriceBar(
                    symbol=symbol,
                    timestamp=current,
                    open=close - 0.5,
                    high=close + 1.0,
                    low=close - 1.0,
                    close=close,
                    volume=6000 if 70 <= index % 120 <= 78 else 2600,
                    timeframe=timeframe,
                )
            )
            current += timedelta(days=1)
            if current > end:
                break
        return [bar for bar in bars if start <= bar.timestamp <= end]

    def fetch_sectors(self, *, as_of, progress_callback=None):
        return {"AKBNK": "banking", "YKBNK": "banking"}

    def fetch_corporate_actions(self, *, start=None, end=None):
        return []

    def run_data_quality_check(self):
        return []


def test_generate_walk_forward_windows_default_shape() -> None:
    windows = generate_walk_forward_windows(end_date=datetime(2026, 3, 27, tzinfo=UTC).date())

    assert len(windows) >= 1
    assert windows[0].train_end < windows[0].test_start
    assert all(
        right.train_start == left.train_start + timedelta(days=30)
        for left, right in zip(windows, windows[1:])
    )


def test_legacy_research_cache_is_ignored_without_crashing(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "research_state.json").write_text(
        json.dumps(
            {
                "cached_at": "2026-03-27T10:00:00+00:00",
                "research_timeframe": "4h",
                "symbol_sectors": {"AKBNK": "banking"},
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(cache_dir=str(cache_dir), persist_runtime_state=True)
    store = InMemoryStore(settings, market_data_provider=None, seed_demo_data=False)

    assert store.strategy_scores == {}
    assert store.setups == {}


def test_build_real_research_state_emits_walk_forward_scores(monkeypatch) -> None:
    settings = Settings(
        research_timeframe="1d",
        backtest_lookback_days=300,
        backtest_min_daily_bars=180,
        min_cluster_size=8,
        walk_forward_train_days=120,
        walk_forward_test_days=30,
        walk_forward_step_days=30,
    )
    provider = WalkForwardProvider()

    monkeypatch.setattr(
        "bistbot.services.research.select_active_strategies",
        lambda scores, **kwargs: [max(scores, key=lambda item: item.trade_count)] if scores else [],
    )

    result = build_real_research_state(provider=provider, settings=settings)

    assert result.strategy_scores
    assert all(score.backtest_mode == "walk_forward" for score in result.strategy_scores.values())
    assert all(score.walk_forward_window_count >= 1 for score in result.strategy_scores.values())
    assert all(len(score.oos_window_trade_counts) == score.walk_forward_window_count for score in result.strategy_scores.values())
