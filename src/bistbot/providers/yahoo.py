from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import yfinance as yf

from bistbot.domain.enums import CorporateActionType
from bistbot.domain.models import CorporateAction, DataQualityEvent, PriceBar
from bistbot.providers.base import MarketDataProvider
from bistbot.providers.company_universe import DEFAULT_YAHOO_RUNTIME_SYMBOLS


DEFAULT_BIST_SECTORS: dict[str, str] = {
    "AKBNK": "banking",
    "GARAN": "banking",
    "ISCTR": "banking",
    "YKBNK": "banking",
    "KCHOL": "holding",
    "SAHOL": "holding",
    "SISE": "industrial",
    "TUPRS": "energy",
    "PETKM": "energy",
    "THYAO": "transportation",
}

BIST_TIMEZONE = ZoneInfo("Europe/Istanbul")
YAHOO_SECTOR_NORMALIZATION: dict[str, str] = {
    "basic-materials": "basic_materials",
    "communication-services": "communication_services",
    "consumer-cyclical": "consumer_cyclical",
    "consumer-defensive": "consumer_defensive",
    "energy": "energy",
    "financial-services": "financial_services",
    "healthcare": "healthcare",
    "industrials": "industrials",
    "real-estate": "real_estate",
    "technology": "technology",
    "utilities": "utilities",
}


@dataclass(slots=True)
class CachedBars:
    fetched_at: datetime
    bars: list[PriceBar]


def normalize_bist_symbol(symbol: str) -> str:
    if "." in symbol:
        return symbol.upper()
    return f"{symbol.upper()}.IS"


def denormalize_bist_symbol(symbol: str) -> str:
    return symbol.replace(".IS", "").upper()


def timeframe_to_yfinance_interval(timeframe: str) -> str:
    mapping = {
        "1h": "60m",
        "1d": "1d",
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return mapping[timeframe]


class YahooFinanceBISTProvider(MarketDataProvider):
    def __init__(
        self,
        *,
        symbols: tuple[str, ...] | list[str] | None = None,
        sector_map: dict[str, str] | None = None,
        cache_ttl_seconds: int = 900,
        cache_dir: str | Path = ".cache/bistbot",
    ) -> None:
        self.symbols = tuple(sorted(symbols or DEFAULT_YAHOO_RUNTIME_SYMBOLS))
        self.sector_map = dict(sector_map or DEFAULT_BIST_SECTORS)
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._bars_cache: dict[tuple[str, str, str, str], CachedBars] = {}
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bars_cache_dir = self.cache_dir / "bars"
        self.bars_cache_dir.mkdir(parents=True, exist_ok=True)
        self.sector_cache_path = self.cache_dir / "sectors.json"
        self._sector_cache = self._load_sector_cache()

    def fetch_symbols(self) -> list[str]:
        return list(self.symbols)

    def fetch_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        force_refresh: bool = False,
    ) -> list[PriceBar]:
        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        normalized_symbol = normalize_bist_symbol(symbol)
        cache_key = (
            normalized_symbol,
            timeframe,
            start_utc.isoformat(),
            end_utc.isoformat(),
        )
        cached = self._bars_cache.get(cache_key)
        now = datetime.now(UTC)
        if cached and not force_refresh and now - cached.fetched_at <= self.cache_ttl:
            return cached.bars

        if timeframe == "4h":
            source_bars = self.fetch_bars(
                symbol,
                timeframe="1h",
                start=start_utc - timedelta(days=2),
                end=end_utc,
                force_refresh=force_refresh,
            )
            aggregated = self._aggregate_four_hour_bars(symbol=symbol, bars=source_bars)
            bars = [
                bar
                for bar in aggregated
                if start_utc <= bar.timestamp <= end_utc
            ]
            self._bars_cache[cache_key] = CachedBars(fetched_at=now, bars=bars)
            return bars

        interval = timeframe_to_yfinance_interval(timeframe)

        all_cached_bars = self._load_disk_bars(symbol=symbol, timeframe=timeframe)
        merged_bars = list(all_cached_bars)
        overlap = timedelta(days=3) if timeframe == "1d" else timedelta(hours=6)
        freshness = timedelta(hours=18) if timeframe == "1d" else timedelta(minutes=45)

        if merged_bars:
            earliest_cached = merged_bars[0].timestamp
            latest_cached = merged_bars[-1].timestamp
            if start_utc < earliest_cached:
                historical_end = min(end_utc, earliest_cached + overlap)
                historical_bars = self._download_bars(
                    normalized_symbol=normalized_symbol,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start_utc,
                    end=historical_end,
                    interval=interval,
                )
                merged_bars = self._merge_bars(historical_bars, merged_bars)
            if force_refresh or end_utc > latest_cached + freshness:
                recent_start = max(start_utc, latest_cached - overlap)
                recent_bars = self._download_bars(
                    normalized_symbol=normalized_symbol,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=recent_start,
                    end=end_utc,
                    interval=interval,
                )
                merged_bars = self._merge_bars(merged_bars, recent_bars)
        else:
            merged_bars = self._download_bars(
                normalized_symbol=normalized_symbol,
                symbol=symbol,
                timeframe=timeframe,
                start=start_utc,
                end=end_utc,
                interval=interval,
            )

        if merged_bars and merged_bars != all_cached_bars:
            self._save_disk_bars(symbol=symbol, timeframe=timeframe, bars=merged_bars)

        bars = [
            bar
            for bar in merged_bars
            if start_utc <= bar.timestamp <= end_utc
        ]
        self._bars_cache[cache_key] = CachedBars(fetched_at=now, bars=bars)
        return bars

    def fetch_sectors(
        self,
        *,
        as_of: date,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        missing: list[str] = []

        for symbol in self.symbols:
            if symbol in self.sector_map:
                resolved[symbol] = self.sector_map[symbol]
                continue
            cached = self._sector_cache.get(symbol)
            if cached:
                resolved[symbol] = cached
                continue
            missing.append(symbol)

        cache_updated = False
        if missing:
            _emit_sector_progress(progress_callback, 3, 0, len(missing))
            max_workers = min(12, max(1, len(missing)))
            completed = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._resolve_sector_from_yahoo, symbol): symbol
                    for symbol in missing
                }
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        sector = future.result()
                    except Exception:
                        sector = None
                    resolved_sector = sector or "unknown"
                    self._sector_cache[symbol] = resolved_sector
                    resolved[symbol] = resolved_sector
                    cache_updated = True
                    completed += 1
                    _emit_sector_progress(progress_callback, 3, completed, len(missing))

        if cache_updated:
            self._save_sector_cache()

        return {symbol: resolved.get(symbol, "unknown") for symbol in self.symbols}

    def fetch_corporate_actions(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[CorporateAction]:
        start_utc = _ensure_utc(start) if start else None
        end_utc = _ensure_utc(end) if end else None
        actions: list[CorporateAction] = []
        for symbol in self.fetch_symbols():
            try:
                ticker = yf.Ticker(normalize_bist_symbol(symbol))
                raw_actions = ticker.actions
            except Exception:
                continue
            if raw_actions is None or raw_actions.empty:
                continue
            for timestamp, row in raw_actions.iterrows():
                action_time = _ensure_utc(timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp)
                if start_utc and action_time < start_utc:
                    continue
                if end_utc and action_time > end_utc:
                    continue

                dividends = float(row.get("Dividends", 0.0))
                splits = float(row.get("Stock Splits", 0.0))
                if splits not in (0.0, 1.0):
                    actions.append(
                        CorporateAction(
                            symbol=symbol,
                            action_type=CorporateActionType.SPLIT,
                            effective_at=action_time,
                            factor=splits,
                            reference=f"yahoo-split:{symbol}:{action_time.date()}",
                        )
                    )
                if dividends > 0:
                    actions.append(
                        CorporateAction(
                            symbol=symbol,
                            action_type=CorporateActionType.CASH_DIVIDEND,
                            effective_at=action_time,
                            cash_amount=dividends,
                            reference=f"yahoo-dividend:{symbol}:{action_time.date()}",
                        )
                    )
        return actions

    def run_data_quality_check(self) -> list[DataQualityEvent]:
        return []

    def _download_bars(
        self,
        *,
        normalized_symbol: str,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> list[PriceBar]:
        try:
            ticker = yf.Ticker(normalized_symbol)
            if timeframe == "1h":
                lookback_days = max(
                    7,
                    min(729, math.ceil((end - start).total_seconds() / 86400) + 2),
                )
                history = ticker.history(
                    period=f"{lookback_days}d",
                    interval=interval,
                    auto_adjust=False,
                    actions=False,
                )
            else:
                history = ticker.history(
                    start=start,
                    end=end + timedelta(days=1),
                    interval=interval,
                    auto_adjust=False,
                    actions=False,
                )
        except Exception:
            return []

        if history is None or history.empty:
            return []

        bars: list[PriceBar] = []
        for timestamp, row in history.iterrows():
            if any(column not in row for column in ("Open", "High", "Low", "Close", "Volume")):
                continue
            bar_timestamp = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp
            bars.append(
                PriceBar(
                    symbol=denormalize_bist_symbol(symbol),
                    timestamp=_ensure_utc(bar_timestamp),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                    timeframe=timeframe,
                )
            )
        bars.sort(key=lambda item: item.timestamp)
        return bars

    def _merge_bars(self, left: list[PriceBar], right: list[PriceBar]) -> list[PriceBar]:
        merged: dict[datetime, PriceBar] = {}
        for bar in left + right:
            merged[bar.timestamp] = bar
        return [merged[timestamp] for timestamp in sorted(merged)]

    def _load_disk_bars(self, *, symbol: str, timeframe: str) -> list[PriceBar]:
        path = self._bar_cache_path(symbol=symbol, timeframe=timeframe)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return []

        bars: list[PriceBar] = []
        for item in payload.get("bars", []):
            try:
                bars.append(
                    PriceBar(
                        symbol=str(item["symbol"]),
                        timestamp=_ensure_utc(datetime.fromisoformat(item["timestamp"])),
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=float(item["volume"]),
                        timeframe=str(item["timeframe"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        bars.sort(key=lambda item: item.timestamp)
        return bars

    def _save_disk_bars(self, *, symbol: str, timeframe: str, bars: list[PriceBar]) -> None:
        path = self._bar_cache_path(symbol=symbol, timeframe=timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "bars": [
                {
                    "symbol": bar.symbol,
                    "timestamp": _ensure_utc(bar.timestamp).isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "timeframe": bar.timeframe,
                }
                for bar in bars
            ],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def _bar_cache_path(self, *, symbol: str, timeframe: str) -> Path:
        return self.bars_cache_dir / timeframe / f"{symbol.upper()}.json"

    def _load_sector_cache(self) -> dict[str, str]:
        if not self.sector_cache_path.exists():
            return {}
        try:
            payload = json.loads(self.sector_cache_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        sectors = payload.get("sectors", {})
        if not isinstance(sectors, dict):
            return {}
        return {
            str(symbol).upper(): str(sector)
            for symbol, sector in sectors.items()
            if sector
        }

    def _save_sector_cache(self) -> None:
        payload = {
            "sectors": dict(sorted(self._sector_cache.items())),
        }
        self.sector_cache_path.write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def _resolve_sector_from_yahoo(self, symbol: str) -> str | None:
        try:
            info = yf.Ticker(normalize_bist_symbol(symbol)).get_info()
        except Exception:
            return None
        if not isinstance(info, dict):
            return None
        return self._normalize_yahoo_sector(info)

    def _normalize_yahoo_sector(self, info: dict[str, Any]) -> str | None:
        industry_key = _normalize_key(
            info.get("industryKey")
            or info.get("industryDisp")
            or info.get("industry")
        )
        sector_key = _normalize_key(
            info.get("sectorKey")
            or info.get("sectorDisp")
            or info.get("sector")
        )

        if "bank" in industry_key:
            return "banking"
        if "capital-markets" in industry_key or "asset-management" in industry_key:
            return "financial_services"
        if "insurance" in industry_key:
            return "insurance"
        if "conglomerate" in industry_key:
            return "holding"
        if any(
            token in industry_key
            for token in ("airline", "airport", "rail", "shipping", "logistics", "freight")
        ):
            return "transportation"
        if "oil-gas" in industry_key or "energy" in industry_key:
            return "energy"
        if "real-estate" in industry_key or sector_key == "real-estate":
            return "real_estate"

        if sector_key in YAHOO_SECTOR_NORMALIZATION:
            return YAHOO_SECTOR_NORMALIZATION[sector_key]
        if sector_key:
            return sector_key.replace("-", "_")
        if industry_key:
            return industry_key.replace("-", "_")
        return None

    def _aggregate_four_hour_bars(
        self,
        *,
        symbol: str,
        bars: list[PriceBar],
    ) -> list[PriceBar]:
        if not bars:
            return []

        grouped_by_day: dict[str, list[PriceBar]] = {}
        for bar in sorted(bars, key=lambda item: item.timestamp):
            local_time = _ensure_utc(bar.timestamp).astimezone(BIST_TIMEZONE)
            grouped_by_day.setdefault(local_time.date().isoformat(), []).append(bar)

        aggregated: list[PriceBar] = []
        for day_bars in grouped_by_day.values():
            for index in range(0, len(day_bars), 4):
                chunk = day_bars[index : index + 4]
                if len(chunk) < 2:
                    continue
                aggregated.append(
                    PriceBar(
                        symbol=symbol.upper(),
                        timestamp=chunk[0].timestamp,
                        open=chunk[0].open,
                        high=max(bar.high for bar in chunk),
                        low=min(bar.low for bar in chunk),
                        close=chunk[-1].close,
                        volume=sum(bar.volume for bar in chunk),
                        timeframe="4h",
                    )
                )
        aggregated.sort(key=lambda item: item.timestamp)
        return aggregated


def _ensure_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _emit_sector_progress(
    callback: Callable[[int, str], None] | None,
    base_percent: int,
    completed: int,
    total: int,
) -> None:
    if callback is None:
        return
    safe_total = max(total, 1)
    percent = base_percent + int((completed / safe_total) * 7)
    callback(
        max(0, min(100, percent)),
        f"Sektorler zenginlestiriliyor: {completed}/{safe_total}",
    )


def _normalize_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return text.replace("&", "and").replace(" ", "-").replace("/", "-")
