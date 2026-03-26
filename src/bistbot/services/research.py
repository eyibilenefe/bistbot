from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import fmean
from typing import Callable

from bistbot.config import Settings
from bistbot.domain.enums import ClusterFallbackMode, StrategyFamily
from bistbot.domain.models import (
    ClusterDefinition,
    PriceBar,
    SetupCandidate,
    StrategyDefinition,
    StrategyScore,
    SymbolSnapshot,
    TradeRecord,
)
from bistbot.providers.base import MarketDataProvider
from bistbot.services.clustering import assign_point_in_time_clusters
from bistbot.services.costs import CostInputs, estimated_round_trip_cost
from bistbot.services.scoring import score_clusters
from bistbot.services.setup_lifecycle import compute_confluence_score, quality_gate
from bistbot.services.strategy_selection import select_active_strategies


@dataclass(slots=True)
class ResearchBuildResult:
    symbol_sectors: dict[str, str]
    bars_by_symbol: dict[str, list[PriceBar]]
    clusters: dict[str, ClusterDefinition]
    strategies: dict[str, StrategyDefinition]
    strategy_scores: dict[str, StrategyScore]
    cluster_active_strategy_ids: dict[str, list[str]]
    backtest_trades: dict[str, list[TradeRecord]]
    setups: list[SetupCandidate]


@dataclass(slots=True)
class SymbolIndicators:
    ema20: list[float | None]
    ema50: list[float | None]
    rsi14: list[float | None]
    atr14: list[float | None]
    atr14_pct: list[float | None]
    atr60_pct: list[float | None]
    volume_ratio20: list[float | None]
    roc10: list[float | None]
    macd_line: list[float | None]
    macd_signal: list[float | None]
    breakout_high20: list[float | None]


def build_real_research_state(
    *,
    provider: MarketDataProvider,
    settings: Settings,
    progress_callback: Callable[[int, str], None] | None = None,
) -> ResearchBuildResult:
    timeframe = settings.research_timeframe
    timeframe_label = _timeframe_label(timeframe)
    _emit_progress(progress_callback, 2, "Sembol ve sektor listesi aliniyor...")
    end = datetime.now(UTC)
    lookback_days = settings.backtest_lookback_days
    if timeframe == "4h":
        lookback_days = min(lookback_days, 720)
    start = end - timedelta(days=lookback_days)
    symbol_sectors = provider.fetch_sectors(
        as_of=end.date(),
        progress_callback=lambda percent, message: _emit_progress(
            progress_callback,
            percent,
            message,
        ),
    )
    symbols = provider.fetch_symbols()

    bars_by_symbol: dict[str, list[PriceBar]] = {}
    snapshots: list[SymbolSnapshot] = []
    indicators_by_symbol: dict[str, SymbolIndicators] = {}

    total_symbols = max(len(symbols), 1)
    for index, symbol in enumerate(symbols, start=1):
        _emit_progress(
            progress_callback,
            12 + int((index / total_symbols) * 53),
            f"{timeframe_label} veri aliniyor: {symbol} ({index}/{total_symbols})",
        )
        bars = provider.fetch_bars(symbol, timeframe=timeframe, start=start, end=end)
        if len(bars) < settings.backtest_min_daily_bars:
            continue
        bars = sorted(bars, key=lambda bar: bar.timestamp)
        bars_by_symbol[symbol] = bars
        indicators = compute_indicators(bars)
        indicators_by_symbol[symbol] = indicators
        atr_pct = indicators.atr60_pct[-1]
        if atr_pct is None:
            continue
        snapshots.append(
            SymbolSnapshot(
                symbol=symbol,
                sector=symbol_sectors.get(symbol, "unknown"),
                atr_percent_60d=atr_pct,
                as_of=end.date(),
            )
        )

    _emit_progress(progress_callback, 65, "Point-in-time kumeleme hesaplaniyor...")
    clusters_list, assignments = assign_point_in_time_clusters(
        snapshots,
        as_of=end.date(),
        min_cluster_size=settings.min_cluster_size,
    )
    clusters = {cluster.id: cluster for cluster in clusters_list}

    strategy_templates = _strategy_templates()
    strategies: dict[str, StrategyDefinition] = {}
    strategy_scores_raw: list[StrategyScore] = []
    trades_by_strategy: dict[str, list[TradeRecord]] = {}
    total_strategy_runs = max(len(clusters_list) * len(strategy_templates), 1)
    strategy_run_index = 0

    for cluster in clusters_list:
        cluster_symbols = [symbol for symbol in cluster.members if symbol in bars_by_symbol]
        cluster_atr_now = fmean(
            indicators_by_symbol[symbol].atr14_pct[-1] or 0.0 for symbol in cluster_symbols
        ) if cluster_symbols else 0.0
        cluster_atr_baseline = fmean(
            indicators_by_symbol[symbol].atr60_pct[-1] or 0.0 for symbol in cluster_symbols
        ) if cluster_symbols else 0.0

        for template in strategy_templates:
            strategy_run_index += 1
            _emit_progress(
                progress_callback,
                70 + int((strategy_run_index / total_strategy_runs) * 25),
                f"Backtest calisiyor: {cluster.id} / {template.name_tr}",
            )
            strategy_id = f"{cluster.id}:{template.family.value}"
            strategies[strategy_id] = StrategyDefinition(
                id=strategy_id,
                name=f"{cluster.sector.title()} {template.name_tr}",
                family=template.family,
                trend_indicator=template.trend_indicator,
                momentum_indicator=template.momentum_indicator,
                volume_indicator=template.volume_indicator,
            )

            cluster_trades: list[TradeRecord] = []
            for symbol in cluster_symbols:
                cluster_trades.extend(
                    simulate_strategy(
                        strategy_id=strategy_id,
                        symbol=symbol,
                        family=template.family,
                        bars=bars_by_symbol[symbol],
                        indicators=indicators_by_symbol[symbol],
                    )
                )

            cost = estimated_round_trip_cost(
                CostInputs(
                    broker_fee=0.0015,
                    taxes=0.0005,
                    base_slippage=0.0010,
                    atr20_current=cluster_atr_now,
                    atr20_60d_median=cluster_atr_baseline,
                )
            )
            trades_by_strategy[strategy_id] = sorted(cluster_trades, key=lambda trade: trade.entered_at)
            strategy_scores_raw.append(
                summarize_strategy(
                    strategy_id=strategy_id,
                    cluster_id=cluster.id,
                    family=template.family,
                    as_of=end.date(),
                    trades=trades_by_strategy[strategy_id],
                    estimated_cost=cost,
                )
            )

    _emit_progress(progress_callback, 97, "Aktif stratejiler seciliyor...")
    scored = score_clusters(strategy_scores_raw)
    strategy_scores = {score.strategy_id: score for score in scored}

    cluster_active_strategy_ids: dict[str, list[str]] = {}
    for cluster_id in clusters:
        cluster_scores = [score for score in scored if score.cluster_id == cluster_id]
        cluster_active_strategy_ids[cluster_id] = [
            score.strategy_id for score in select_active_strategies(cluster_scores)
        ]

    setups = build_setup_candidates(
        clusters=clusters,
        strategies=strategies,
        strategy_scores=strategy_scores,
        cluster_active_strategy_ids=cluster_active_strategy_ids,
        bars_by_symbol=bars_by_symbol,
        indicators_by_symbol=indicators_by_symbol,
        settings=settings,
    )

    _emit_progress(progress_callback, 96, "Arastirma guncellemesi tamamlandi.")
    return ResearchBuildResult(
        symbol_sectors=symbol_sectors,
        bars_by_symbol=bars_by_symbol,
        clusters=clusters,
        strategies=strategies,
        strategy_scores=strategy_scores,
        cluster_active_strategy_ids=cluster_active_strategy_ids,
        backtest_trades=trades_by_strategy,
        setups=setups,
    )


def _emit_progress(
    callback: Callable[[int, str], None] | None,
    percent: int,
    message: str,
) -> None:
    if callback is None:
        return
    callback(max(0, min(100, int(percent))), message)


def _timeframe_label(timeframe: str) -> str:
    labels = {
        "1d": "Gunluk",
        "1h": "Saatlik",
        "4h": "4 saatlik",
    }
    return labels.get(timeframe, timeframe)


@dataclass(slots=True)
class StrategyTemplate:
    family: StrategyFamily
    name_tr: str
    trend_indicator: str
    momentum_indicator: str
    volume_indicator: str


def _strategy_templates() -> list[StrategyTemplate]:
    return [
        StrategyTemplate(
            family=StrategyFamily.TREND_FOLLOWING,
            name_tr="Trend Takibi",
            trend_indicator="EMA20/50",
            momentum_indicator="MACD",
            volume_indicator="OBV",
        ),
        StrategyTemplate(
            family=StrategyFamily.PULLBACK_MEAN_REVERSION,
            name_tr="Geri Cekilme Tepkisi",
            trend_indicator="EMA50",
            momentum_indicator="RSI",
            volume_indicator="Hacim Orani",
        ),
        StrategyTemplate(
            family=StrategyFamily.BREAKOUT_VOLUME,
            name_tr="Hacimli Kirilim",
            trend_indicator="EMA20",
            momentum_indicator="ROC",
            volume_indicator="Hacim Orani",
        ),
    ]


def compute_indicators(bars: list[PriceBar]) -> SymbolIndicators:
    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    volumes = [bar.volume for bar in bars]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi14 = rsi(closes, 14)
    atr14 = atr(highs, lows, closes, 14)
    atr14_pct = [
        ((atr_value / close) * 100) if atr_value is not None and close > 0 else None
        for atr_value, close in zip(atr14, closes)
    ]
    atr60 = atr(highs, lows, closes, 60)
    atr60_pct = [
        ((atr_value / close) * 100) if atr_value is not None and close > 0 else None
        for atr_value, close in zip(atr60, closes)
    ]
    volume_ma20 = sma(volumes, 20)
    volume_ratio20 = [
        (vol / avg) if avg not in (None, 0) else None
        for vol, avg in zip(volumes, volume_ma20)
    ]
    roc10 = roc(closes, 10)
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = [
        (fast - slow) if fast is not None and slow is not None else None
        for fast, slow in zip(ema12, ema26)
    ]
    macd_signal = ema([value or 0.0 for value in macd_line], 9)
    breakout_high20 = rolling_high(highs, 20)

    return SymbolIndicators(
        ema20=ema20,
        ema50=ema50,
        rsi14=rsi14,
        atr14=atr14,
        atr14_pct=atr14_pct,
        atr60_pct=atr60_pct,
        volume_ratio20=volume_ratio20,
        roc10=roc10,
        macd_line=macd_line,
        macd_signal=macd_signal,
        breakout_high20=breakout_high20,
    )


def signal_components(
    *,
    family: StrategyFamily,
    index: int,
    bars: list[PriceBar],
    indicators: SymbolIndicators,
) -> dict[str, bool]:
    close = bars[index].close
    ema20 = indicators.ema20[index]
    ema50 = indicators.ema50[index]
    rsi_now = indicators.rsi14[index]
    rsi_prev = indicators.rsi14[index - 1]
    macd_now = indicators.macd_line[index]
    macd_signal = indicators.macd_signal[index]
    vol_ratio = indicators.volume_ratio20[index]
    breakout_prev = indicators.breakout_high20[index - 1]
    roc_now = indicators.roc10[index]
    prev_close = bars[index - 1].close
    prev_ema20 = indicators.ema20[index - 1]

    if family == StrategyFamily.TREND_FOLLOWING:
        return {
            "daily_regime_valid": bool(
                ema20 is not None and ema50 is not None and close > ema20 > ema50
            ),
            "trend_signal": bool(ema20 is not None and ema50 is not None and close > ema20 > ema50),
            "momentum_signal": bool(
                rsi_now is not None
                and macd_now is not None
                and macd_signal is not None
                and rsi_now > 55
                and macd_now > macd_signal
            ),
            "volume_confirmation": bool(vol_ratio is not None and vol_ratio > 1.0),
        }

    if family == StrategyFamily.PULLBACK_MEAN_REVERSION:
        return {
            "daily_regime_valid": bool(ema50 is not None and close > ema50),
            "trend_signal": bool(
                ema20 is not None
                and ema50 is not None
                and prev_ema20 is not None
                and close > ema50
                and prev_close < prev_ema20
                and close > ema20
            ),
            "momentum_signal": bool(
                rsi_now is not None
                and rsi_prev is not None
                and rsi_prev < 45 <= rsi_now
            ),
            "volume_confirmation": bool(vol_ratio is not None and vol_ratio > 0.9),
        }

    return {
        "daily_regime_valid": bool(ema20 is not None and close > ema20),
        "trend_signal": bool(
            ema20 is not None
            and breakout_prev is not None
            and close > ema20
            and close > breakout_prev
        ),
        "momentum_signal": bool(roc_now is not None and roc_now > 0),
        "volume_confirmation": bool(vol_ratio is not None and vol_ratio > 1.3),
    }


def simulate_strategy(
    *,
    strategy_id: str,
    symbol: str,
    family: StrategyFamily,
    bars: list[PriceBar],
    indicators: SymbolIndicators,
) -> list[TradeRecord]:
    trades: list[TradeRecord] = []
    position: dict[str, object] | None = None

    for index in range(60, len(bars)):
        bar = bars[index]
        prev_bar = bars[index - 1]
        current_signal = strategy_signal(family=family, index=index, bars=bars, indicators=indicators)

        if position is None and current_signal:
            entry_price = bar.close
            atr_value = indicators.atr14[index]
            if atr_value is None or atr_value <= 0:
                continue
            risk = atr_value * 1.5
            position = {
                "entry_index": index,
                "entry_time": bar.timestamp,
                "entry_price": entry_price,
                "stop": entry_price - risk,
                "risk": risk,
                "bars_held": 0,
            }
            continue

        if position is None:
            continue

        position["bars_held"] = int(position["bars_held"]) + 1
        entry_price = float(position["entry_price"])
        risk = float(position["risk"])
        stop = float(position["stop"])

        if bar.low <= stop:
            exit_price = stop
            trades.append(
                build_trade_record(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    entry_time=position["entry_time"],
                    exit_time=bar.timestamp,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    risk=risk,
                )
            )
            position = None
            continue

        if bar.close >= entry_price + risk:
            stop = max(stop, entry_price)
        if bar.close >= entry_price + (2 * risk):
            stop = max(stop, entry_price + risk)
        position["stop"] = stop

        should_exit = strategy_exit(
            family=family,
            index=index,
            bars=bars,
            indicators=indicators,
            bars_held=int(position["bars_held"]),
            entry_price=entry_price,
            risk=risk,
        )
        if should_exit:
            trades.append(
                build_trade_record(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    entry_time=position["entry_time"],
                    exit_time=bar.timestamp,
                    entry_price=entry_price,
                    exit_price=bar.close,
                    risk=risk,
                )
            )
            position = None

    return trades


def strategy_signal(
    *,
    family: StrategyFamily,
    index: int,
    bars: list[PriceBar],
    indicators: SymbolIndicators,
) -> bool:
    components = signal_components(
        family=family,
        index=index,
        bars=bars,
        indicators=indicators,
    )
    return bool(
        components["trend_signal"]
        and components["momentum_signal"]
        and components["volume_confirmation"]
    )


def find_recent_signal_index(
    *,
    family: StrategyFamily,
    bars: list[PriceBar],
    indicators: SymbolIndicators,
    lookback_bars: int,
) -> int | None:
    start_index = max(60, len(bars) - lookback_bars)
    for index in range(len(bars) - 1, start_index - 1, -1):
        if strategy_signal(family=family, index=index, bars=bars, indicators=indicators):
            return index
    return None


def strategy_exit(
    *,
    family: StrategyFamily,
    index: int,
    bars: list[PriceBar],
    indicators: SymbolIndicators,
    bars_held: int,
    entry_price: float,
    risk: float,
) -> bool:
    close = bars[index].close
    high = bars[index].high
    ema20 = indicators.ema20[index]
    ema50 = indicators.ema50[index]

    if family == StrategyFamily.TREND_FOLLOWING:
        trend_valid = ema20 is not None and ema50 is not None and close > ema20 and ema20 > ema50
        if high >= entry_price + (2 * risk) and not trend_valid:
            return True
        return (bars_held >= 7 and not trend_valid) or (ema20 is not None and close < ema20)

    if family == StrategyFamily.PULLBACK_MEAN_REVERSION:
        return (
            high >= entry_price + (2 * risk)
            or bars_held >= 10
            or (ema50 is not None and close < ema50)
        )

    return (
        high >= entry_price + (2 * risk)
        or bars_held >= 12
        or (ema20 is not None and close < ema20)
    )


def build_trade_record(
    *,
    strategy_id: str,
    symbol: str,
    entry_time: datetime,
    exit_time: datetime,
    entry_price: float,
    exit_price: float,
    risk: float,
) -> TradeRecord:
    return_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0
    r_multiple = (exit_price - entry_price) / risk if risk else 0.0
    return TradeRecord(
        strategy_id=strategy_id,
        symbol=symbol,
        entered_at=entry_time,
        exited_at=exit_time,
        return_pct=return_pct,
        r_multiple=r_multiple,
        entry_price=entry_price,
        exit_price=exit_price,
    )


@dataclass(slots=True)
class SymbolTradeSummary:
    total_return: float
    max_drawdown: float
    window_counts: list[int]
    window_returns: list[float]


def summarize_strategy(
    *,
    strategy_id: str,
    cluster_id: str,
    family: StrategyFamily,
    as_of: date,
    trades: list[TradeRecord],
    estimated_cost: float,
) -> StrategyScore:
    if not trades:
        return StrategyScore(
            strategy_id=strategy_id,
            cluster_id=cluster_id,
            as_of=as_of,
            family=family,
            total_return=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            max_drawdown=1.0,
            trade_count=0,
            avg_trade_return=0.0,
            estimated_round_trip_cost=estimated_cost,
            oos_window_trade_counts=[0, 0, 0, 0, 0, 0],
            oos_returns=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )

    returns = [trade.return_pct for trade in trades]
    wins = [value for value in returns if value > 0]
    losses = [abs(value) for value in returns if value < 0]
    win_rate = len(wins) / len(returns) if returns else 0.0
    profit_factor = (sum(wins) / sum(losses)) if losses else float(len(wins) or 0)
    avg_trade_return = fmean(returns)

    per_symbol = [
        summarize_symbol_trade_history(symbol_trades)
        for symbol_trades in _group_trades_by_symbol(trades).values()
        if symbol_trades
    ]
    total_return = fmean(summary.total_return for summary in per_symbol) if per_symbol else 0.0
    max_drawdown = percentile(
        [summary.max_drawdown for summary in per_symbol],
        0.75,
    ) if per_symbol else 1.0
    window_counts = [
        sum(summary.window_counts[index] for summary in per_symbol)
        for index in range(6)
    ] if per_symbol else [0, 0, 0, 0, 0, 0]
    window_returns = [
        fmean(summary.window_returns[index] for summary in per_symbol)
        for index in range(6)
    ] if per_symbol else [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    return StrategyScore(
        strategy_id=strategy_id,
        cluster_id=cluster_id,
        as_of=as_of,
        family=family,
        total_return=total_return,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        trade_count=len(trades),
        avg_trade_return=avg_trade_return,
        estimated_round_trip_cost=estimated_cost,
        oos_window_trade_counts=window_counts,
        oos_returns=window_returns,
    )


def _group_trades_by_symbol(trades: list[TradeRecord]) -> dict[str, list[TradeRecord]]:
    grouped: dict[str, list[TradeRecord]] = {}
    for trade in trades:
        grouped.setdefault(trade.symbol, []).append(trade)
    for symbol_trades in grouped.values():
        symbol_trades.sort(key=lambda trade: trade.exited_at)
    return grouped


def summarize_symbol_trade_history(trades: list[TradeRecord]) -> SymbolTradeSummary:
    sorted_trades = sorted(trades, key=lambda trade: trade.exited_at)
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for trade in sorted_trades:
        equity *= (1 + trade.return_pct)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    recent_end = datetime.now(UTC)
    window_counts: list[int] = []
    window_returns: list[float] = []
    for window_index in range(5, -1, -1):
        window_end = recent_end - timedelta(days=window_index * 30)
        window_start = window_end - timedelta(days=30)
        window_trades = [
            trade for trade in sorted_trades if window_start <= trade.exited_at < window_end
        ]
        window_counts.append(len(window_trades))
        window_returns.append(sum(trade.return_pct for trade in window_trades))

    return SymbolTradeSummary(
        total_return=equity - 1,
        max_drawdown=max_drawdown,
        window_counts=window_counts,
        window_returns=window_returns,
    )


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    q = min(max(q, 0.0), 1.0)
    position = q * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def build_setup_candidates(
    *,
    clusters: dict[str, ClusterDefinition],
    strategies: dict[str, StrategyDefinition],
    strategy_scores: dict[str, StrategyScore],
    cluster_active_strategy_ids: dict[str, list[str]],
    bars_by_symbol: dict[str, list[PriceBar]],
    indicators_by_symbol: dict[str, SymbolIndicators],
    settings: Settings,
) -> list[SetupCandidate]:
    candidates: list[SetupCandidate] = []
    now = datetime.now(UTC)

    for cluster_id, strategy_ids in cluster_active_strategy_ids.items():
        cluster = clusters.get(cluster_id)
        if cluster is None:
            continue
        for strategy_id in strategy_ids:
            strategy = strategies.get(strategy_id)
            strategy_score = strategy_scores.get(strategy_id)
            if strategy is None or strategy_score is None:
                continue
            for symbol in cluster.members:
                bars = bars_by_symbol.get(symbol)
                indicators = indicators_by_symbol.get(symbol)
                if not bars or indicators is None or len(bars) < 60:
                    continue
                index = find_recent_signal_index(
                    family=strategy.family,
                    bars=bars,
                    indicators=indicators,
                    lookback_bars=3,
                )
                if index is None:
                    continue
                components = signal_components(
                    family=strategy.family,
                    index=index,
                    bars=bars,
                    indicators=indicators,
                )
                atr_value = indicators.atr14[index]
                if atr_value is None or atr_value <= 0:
                    continue
                last_close = bars[-1].close
                signal_close = bars[index].close
                entry_zone_proximity = max(
                    0.0,
                    1.0 - min(abs(last_close - signal_close) / atr_value, 1.0),
                )
                entry_low = max(last_close - (atr_value * 0.25), 0.01)
                entry_high = last_close + (atr_value * 0.25)
                target = last_close + (atr_value * 3.0)
                confluence = compute_confluence_score(
                    daily_regime_valid=components["daily_regime_valid"],
                    trend_signal=components["trend_signal"],
                    momentum_signal=components["momentum_signal"],
                    volume_confirmation=components["volume_confirmation"],
                    entry_zone_proximity=entry_zone_proximity,
                )
                score = max(strategy_score.composite_score, 0.0) + confluence
                candidates.append(
                    SetupCandidate(
                        id=f"{strategy_id}:{symbol}",
                        symbol=symbol,
                        cluster_id=cluster_id,
                        strategy_id=strategy_id,
                        strategy_family=strategy.family,
                        score=score,
                        entry_low=entry_low,
                        entry_high=entry_high,
                        stop=max(last_close - (atr_value * 1.5), 0.01),
                        target=target,
                        confidence=min(0.99, 0.55 + (confluence * 0.35)),
                        confluence_score=confluence,
                        expected_r=2.0,
                        created_at=now,
                        expires_at=now + timedelta(hours=settings.setup_expiration_hours),
                    )
                )

    return quality_gate(candidates, top_percent=settings.quality_gate_percentile)


def ema(values: list[float], period: int) -> list[float | None]:
    alpha = 2 / (period + 1)
    result: list[float | None] = []
    current: float | None = None
    for value in values:
        current = value if current is None else (alpha * value) + ((1 - alpha) * current)
        result.append(current)
    return result


def sma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        if index >= period - 1:
            result.append(running / period)
        else:
            result.append(None)
    return result


def rsi(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result

    gains = [0.0] * len(values)
    losses = [0.0] * len(values)
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        gains[index] = max(delta, 0.0)
        losses[index] = max(-delta, 0.0)

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for index in range(period + 1, len(values)):
        avg_gain = ((avg_gain * (period - 1)) + gains[index]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[index]) / period
        result[index] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if math.isclose(avg_loss, 0.0):
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> list[float | None]:
    true_ranges: list[float] = []
    for index, (high, low) in enumerate(zip(highs, lows)):
        if index == 0:
            true_ranges.append(high - low)
            continue
        prev_close = closes[index - 1]
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sma(true_ranges, period)


def roc(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    for index, value in enumerate(values):
        if index < period or math.isclose(values[index - period], 0.0):
            result.append(None)
            continue
        result.append((value / values[index - period]) - 1)
    return result


def rolling_high(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        if index < period:
            result.append(None)
            continue
        result.append(max(values[index - period : index]))
    return result
