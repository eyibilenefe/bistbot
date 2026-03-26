from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from datetime import UTC, datetime, timedelta

from bistbot.domain.models import PriceBar
from bistbot.providers.company_universe import (
    BIST_DOCUMENT_SYMBOLS,
    DEFAULT_YAHOO_RUNTIME_SYMBOLS,
    YAHOO_EXCLUDED_SYMBOLS,
)
from bistbot.providers.yahoo import (
    YahooFinanceBISTProvider,
    denormalize_bist_symbol,
    normalize_bist_symbol,
    timeframe_to_yfinance_interval,
)


def test_bist_symbol_normalization() -> None:
    assert normalize_bist_symbol("akbnk") == "AKBNK.IS"
    assert normalize_bist_symbol("THYAO.IS") == "THYAO.IS"
    assert denormalize_bist_symbol("KCHOL.IS") == "KCHOL"


def test_timeframe_mapping_for_yfinance() -> None:
    assert timeframe_to_yfinance_interval("1h") == "60m"
    assert timeframe_to_yfinance_interval("1d") == "1d"


def test_default_provider_uses_static_pdf_universe() -> None:
    provider = YahooFinanceBISTProvider()

    symbols = provider.fetch_symbols()

    assert len(BIST_DOCUMENT_SYMBOLS) >= 700
    assert symbols == sorted(DEFAULT_YAHOO_RUNTIME_SYMBOLS)
    assert "AKBNK" in symbols
    assert "THYAO" in symbols
    assert "SISE" in symbols
    assert "YKYAT" not in symbols
    assert "ADLVY" not in symbols


def test_runtime_universe_excludes_known_yahoo_failures() -> None:
    assert len(YAHOO_EXCLUDED_SYMBOLS) > 50
    assert "YKYAT" in YAHOO_EXCLUDED_SYMBOLS
    assert "OTKAR" in YAHOO_EXCLUDED_SYMBOLS
    assert "PBTR" in YAHOO_EXCLUDED_SYMBOLS
    assert "YKYAT" not in DEFAULT_YAHOO_RUNTIME_SYMBOLS
    assert "AKBNK" in DEFAULT_YAHOO_RUNTIME_SYMBOLS


def test_provider_returns_unknown_sector_for_unclassified_symbols() -> None:
    provider = YahooFinanceBISTProvider(symbols=("AKBNK", "A1CAP"))
    provider._resolve_sector_from_yahoo = lambda symbol: "financial_services" if symbol == "A1CAP" else None  # type: ignore[method-assign]

    sectors = provider.fetch_sectors(as_of=None)  # type: ignore[arg-type]

    assert sectors["AKBNK"] == "banking"
    assert sectors["A1CAP"] == "financial_services"


def test_provider_reports_sector_progress_during_resolution() -> None:
    with TemporaryDirectory() as tmp_dir:
        provider = YahooFinanceBISTProvider(
            symbols=("A1CAP",),
            sector_map={},
            cache_dir=tmp_dir,
        )
        provider._resolve_sector_from_yahoo = lambda symbol: "financial_services"  # type: ignore[method-assign]
        updates: list[tuple[int, str]] = []

        sectors = provider.fetch_sectors(
            as_of=None,  # type: ignore[arg-type]
            progress_callback=lambda percent, message: updates.append((percent, message)),
        )

        assert sectors["A1CAP"] == "financial_services"
        assert updates
        assert updates[0][0] >= 3
        assert updates[-1][0] > updates[0][0]
        assert "Sektorler zenginlestiriliyor" in updates[-1][1]


def test_provider_can_persist_sector_cache_between_instances() -> None:
    with TemporaryDirectory() as tmp_dir:
        provider = YahooFinanceBISTProvider(
            symbols=("A1CAP",),
            cache_dir=tmp_dir,
            sector_map={},
        )

        provider._sector_cache["A1CAP"] = "financial_services"
        provider._save_sector_cache()

        another = YahooFinanceBISTProvider(
            symbols=("A1CAP",),
            cache_dir=tmp_dir,
            sector_map={},
        )

        sectors = another.fetch_sectors(as_of=None)  # type: ignore[arg-type]

        assert sectors["A1CAP"] == "financial_services"
        payload = json.loads(Path(tmp_dir, "sectors.json").read_text(encoding="utf-8"))
        assert payload["sectors"]["A1CAP"] == "financial_services"


def test_provider_normalizes_yahoo_sector_and_industry_into_internal_groups() -> None:
    provider = YahooFinanceBISTProvider(symbols=("AKBNK",), sector_map={})

    assert provider._normalize_yahoo_sector({"industry": "Banks - Regional"}) == "banking"
    assert provider._normalize_yahoo_sector({"industryKey": "conglomerates"}) == "holding"
    assert provider._normalize_yahoo_sector({"sectorKey": "consumer-defensive"}) == "consumer_defensive"


def test_provider_can_aggregate_hourly_bars_into_four_hour_bars() -> None:
    provider = YahooFinanceBISTProvider(symbols=("AKBNK",))
    start = datetime(2026, 1, 5, 10, tzinfo=UTC)
    hourly_bars = [
        PriceBar(
            symbol="AKBNK",
            timestamp=start + timedelta(hours=index),
            open=10 + index,
            high=10.5 + index,
            low=9.5 + index,
            close=10.2 + index,
            volume=1000 + index,
            timeframe="1h",
        )
        for index in range(8)
    ]

    bars_4h = provider._aggregate_four_hour_bars(symbol="AKBNK", bars=hourly_bars)

    assert len(bars_4h) == 2
    assert bars_4h[0].timeframe == "4h"
    assert bars_4h[0].open == hourly_bars[0].open
    assert bars_4h[0].close == hourly_bars[3].close
    assert bars_4h[1].close == hourly_bars[7].close
