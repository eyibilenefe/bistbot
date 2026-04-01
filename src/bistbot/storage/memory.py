from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from statistics import fmean
from typing import Callable

from bistbot.config import Settings
from bistbot.domain.enums import (
    ClusterFallbackMode,
    LifecycleEventType,
    PositionStatus,
    SetupStatus,
    StrategyFamily,
)
from bistbot.domain.models import (
    ClusterDefinition,
    CorporateAction,
    DashboardOverview,
    LifecycleEvent,
    PriceBar,
    PortfolioPosition,
    ProposedPosition,
    SetupCandidate,
    StrategyDefinition,
    StrategyScore,
    TradeRecord,
)
from bistbot.providers.base import MarketDataProvider
from bistbot.services.charting import (
    build_candlestick_chart,
    build_price_line,
    build_price_marker,
)
from bistbot.services.position_management import should_keep_position_open
from bistbot.services.presentation import (
    build_lifecycle_event_view,
    build_position_entry_reason,
    build_position_view,
    build_setup_thesis,
    build_setup_view,
    build_watchlist_row_view,
    compute_expected_r,
    format_probability_pct,
    is_finite_number,
    normalize_probability,
    require_finite_number,
    require_positive_int,
    require_probability,
    sanitize_chart_payload,
    validate_long_trade_values,
)
from bistbot.services.portfolio_adjustments import adjust_position_for_corporate_action
from bistbot.services.research import build_real_research_state, compute_indicators
from bistbot.services.risk import calculate_position_size, evaluate_position_constraints
from bistbot.services.scoring import is_garbage_strategy, score_clusters
from bistbot.services.setup_lifecycle import (
    approve_setup,
    compute_confluence_score,
    quality_gate,
    refresh_setup_status,
    reject_setup,
)
from bistbot.services.strategy_selection import select_active_strategies
from bistbot.storage.disk_cache import DiskCache

RESEARCH_STATE_SCHEMA_VERSION = 2
MAX_LIFECYCLE_EVENTS = 200


class InMemoryStore:
    def __init__(
        self,
        settings: Settings,
        *,
        market_data_provider: MarketDataProvider | None = None,
        seed_demo_data: bool = False,
    ) -> None:
        self.settings = settings
        self.market_data_provider = market_data_provider
        self.disk_cache = (
            DiskCache(settings.cache_dir)
            if settings.persist_runtime_state and not seed_demo_data
            else None
        )
        self.initial_cash = settings.initial_portfolio_cash
        self.cash_balance = settings.initial_portfolio_cash
        self.symbol_sectors: dict[str, str] = {}
        self.bars_by_symbol: dict[str, list[PriceBar]] = {}
        self.clusters: dict[str, ClusterDefinition] = {}
        self.strategies: dict[str, StrategyDefinition] = {}
        self.strategy_scores: dict[str, StrategyScore] = {}
        self.cluster_active_strategy_ids: dict[str, list[str]] = {}
        self.setups: dict[str, SetupCandidate] = {}
        self.positions: dict[str, PortfolioPosition] = {}
        self.backtest_trades: dict[str, list[TradeRecord]] = {}
        self.lifecycle_events: list[LifecycleEvent] = []
        self.research_cached_at: datetime | None = None
        self._last_live_positions_refresh_at: datetime | None = None
        self._real_data_attempted = seed_demo_data
        self._real_data_loaded = False
        self._event_sequence = 0
        self.correlation_map: dict[tuple[str, str], float] = {
            ("AKBNK", "YKBNK"): 0.82,
            ("AKBNK", "TUPRS"): 0.24,
            ("YKBNK", "TUPRS"): 0.22,
            ("KCHOL", "TUPRS"): 0.61,
        }
        if seed_demo_data:
            self._seed_demo_data()
        else:
            self._load_cached_runtime_state()
            self._load_cached_research_state()
            self._load_real_symbol_metadata()
            self._backfill_position_metadata()
            self._bootstrap_paper_portfolio()

    def _seed_demo_data(self) -> None:
        as_of = date(2026, 3, 25)
        self.clusters = {
            "banking:low": ClusterDefinition(
                id="banking:low",
                sector="banking",
                vol_bucket="low",
                symbol_count=14,
                fallback_mode=ClusterFallbackMode.NONE,
                as_of=as_of,
                members=["AKBNK", "YKBNK", "GARAN", "ISCTR"],
            ),
            "holding:mid": ClusterDefinition(
                id="holding:mid",
                sector="holding",
                vol_bucket="mid",
                symbol_count=11,
                fallback_mode=ClusterFallbackMode.NONE,
                as_of=as_of,
                members=["KCHOL", "SAHOL"],
            ),
            "energy:high": ClusterDefinition(
                id="energy:high",
                sector="energy",
                vol_bucket="high",
                symbol_count=9,
                fallback_mode=ClusterFallbackMode.NONE,
                as_of=as_of,
                members=["TUPRS", "PETKM"],
            ),
        }
        self.symbol_sectors = {
            "AKBNK": "banking",
            "YKBNK": "banking",
            "KCHOL": "holding",
            "TUPRS": "energy",
            "PETKM": "energy",
            "SAHOL": "holding",
        }

        strategies = [
            StrategyDefinition(
                id="strat-trend-bank",
                name="Bank EMA Break",
                family=StrategyFamily.TREND_FOLLOWING,
                trend_indicator="EMA20/50",
                momentum_indicator="MACD",
                volume_indicator="OBV",
            ),
            StrategyDefinition(
                id="strat-pullback-bank",
                name="Bank Pullback Reset",
                family=StrategyFamily.PULLBACK_MEAN_REVERSION,
                trend_indicator="Supertrend",
                momentum_indicator="RSI",
                volume_indicator="Volume MA Ratio",
            ),
            StrategyDefinition(
                id="strat-breakout-bank",
                name="Bank Volume Burst",
                family=StrategyFamily.BREAKOUT_VOLUME,
                trend_indicator="EMA20/50",
                momentum_indicator="ROC",
                volume_indicator="VWAP Deviation",
            ),
            StrategyDefinition(
                id="strat-trend-energy",
                name="Energy Trend Carry",
                family=StrategyFamily.TREND_FOLLOWING,
                trend_indicator="EMA20/50",
                momentum_indicator="MACD",
                volume_indicator="OBV",
            ),
            StrategyDefinition(
                id="strat-pullback-holding",
                name="Holding RSI Snapback",
                family=StrategyFamily.PULLBACK_MEAN_REVERSION,
                trend_indicator="Supertrend",
                momentum_indicator="Stochastic RSI",
                volume_indicator="Volume MA Ratio",
            ),
            StrategyDefinition(
                id="strat-breakout-energy",
                name="Energy Breakout Fuel",
                family=StrategyFamily.BREAKOUT_VOLUME,
                trend_indicator="EMA20/50",
                momentum_indicator="ROC",
                volume_indicator="VWAP Deviation",
            ),
        ]
        self.strategies = {strategy.id: strategy for strategy in strategies}

        cluster_scores = score_clusters(
            [
                StrategyScore(
                    strategy_id="strat-trend-bank",
                    cluster_id="banking:low",
                    as_of=as_of,
                    family=StrategyFamily.TREND_FOLLOWING,
                    total_return=0.34,
                    win_rate=0.59,
                    profit_factor=1.82,
                    max_drawdown=0.11,
                    trade_count=73,
                    avg_trade_return=0.011,
                    estimated_round_trip_cost=0.0035,
                    oos_window_trade_counts=[3, 2, 4, 0, 2, 3],
                    oos_returns=[0.02, 0.03, -0.01, 0.01, 0.04, 0.03],
                ),
                StrategyScore(
                    strategy_id="strat-pullback-bank",
                    cluster_id="banking:low",
                    as_of=as_of,
                    family=StrategyFamily.PULLBACK_MEAN_REVERSION,
                    total_return=0.26,
                    win_rate=0.62,
                    profit_factor=1.61,
                    max_drawdown=0.09,
                    trade_count=68,
                    avg_trade_return=0.010,
                    estimated_round_trip_cost=0.0032,
                    oos_window_trade_counts=[1, 3, 2, 1, 2, 2],
                    oos_returns=[0.01, 0.02, 0.00, 0.02, 0.03, 0.01],
                ),
                StrategyScore(
                    strategy_id="strat-breakout-bank",
                    cluster_id="banking:low",
                    as_of=as_of,
                    family=StrategyFamily.BREAKOUT_VOLUME,
                    total_return=0.29,
                    win_rate=0.54,
                    profit_factor=1.76,
                    max_drawdown=0.10,
                    trade_count=65,
                    avg_trade_return=0.0105,
                    estimated_round_trip_cost=0.0033,
                    oos_window_trade_counts=[2, 2, 2, 1, 2, 2],
                    oos_returns=[0.02, 0.02, -0.005, 0.015, 0.03, 0.025],
                ),
                StrategyScore(
                    strategy_id="strat-trend-energy",
                    cluster_id="energy:high",
                    as_of=as_of,
                    family=StrategyFamily.TREND_FOLLOWING,
                    total_return=0.41,
                    win_rate=0.57,
                    profit_factor=1.95,
                    max_drawdown=0.16,
                    trade_count=80,
                    avg_trade_return=0.013,
                    estimated_round_trip_cost=0.0045,
                    oos_window_trade_counts=[4, 2, 3, 2, 3, 4],
                    oos_returns=[0.03, 0.05, -0.02, 0.01, 0.04, 0.05],
                ),
                StrategyScore(
                    strategy_id="strat-pullback-holding",
                    cluster_id="holding:mid",
                    as_of=as_of,
                    family=StrategyFamily.PULLBACK_MEAN_REVERSION,
                    total_return=0.21,
                    win_rate=0.60,
                    profit_factor=1.52,
                    max_drawdown=0.08,
                    trade_count=61,
                    avg_trade_return=0.009,
                    estimated_round_trip_cost=0.0032,
                    oos_window_trade_counts=[2, 1, 1, 2, 1, 2],
                    oos_returns=[0.015, 0.01, -0.005, 0.02, 0.01, 0.015],
                ),
                StrategyScore(
                    strategy_id="strat-breakout-energy",
                    cluster_id="energy:high",
                    as_of=as_of,
                    family=StrategyFamily.BREAKOUT_VOLUME,
                    total_return=0.35,
                    win_rate=0.53,
                    profit_factor=1.70,
                    max_drawdown=0.12,
                    trade_count=56,
                    avg_trade_return=0.0108,
                    estimated_round_trip_cost=0.0040,
                    oos_window_trade_counts=[2, 1, 2, 1, 2, 2],
                    oos_returns=[0.02, 0.03, -0.01, 0.015, 0.02, 0.025],
                ),
            ]
        )
        self.strategy_scores = {score.strategy_id: score for score in cluster_scores}
        for score in self.strategy_scores.values():
            score.walk_forward_window_count = len(score.oos_window_trade_counts)

        scores_by_cluster: dict[str, list[StrategyScore]] = {}
        for score in cluster_scores:
            scores_by_cluster.setdefault(score.cluster_id, []).append(score)
        self.cluster_active_strategy_ids = {
            cluster_id: [score.strategy_id for score in select_active_strategies(scores)]
            for cluster_id, scores in scores_by_cluster.items()
        }

        now = datetime.now(UTC)
        raw_setups: list[SetupCandidate] = []
        symbols = ["AKBNK", "YKBNK", "KCHOL", "TUPRS", "PETKM", "SAHOL"]
        cluster_ids = ["banking:low", "banking:low", "holding:mid", "energy:high", "energy:high", "holding:mid"]
        strategy_ids = [
            "strat-trend-bank",
            "strat-breakout-bank",
            "strat-pullback-holding",
            "strat-trend-energy",
            "strat-breakout-energy",
            "strat-pullback-holding",
        ]
        families = [
            StrategyFamily.TREND_FOLLOWING,
            StrategyFamily.BREAKOUT_VOLUME,
            StrategyFamily.PULLBACK_MEAN_REVERSION,
            StrategyFamily.TREND_FOLLOWING,
            StrategyFamily.BREAKOUT_VOLUME,
            StrategyFamily.PULLBACK_MEAN_REVERSION,
        ]

        for index in range(30):
            score = 0.98 - (index * 0.02)
            symbol = symbols[index % len(symbols)]
            family = families[index % len(families)]
            cluster_id = cluster_ids[index % len(cluster_ids)]
            base_price = 20 + index
            raw_setups.append(
                SetupCandidate(
                    id=f"setup-{index + 1}",
                    symbol=symbol,
                    cluster_id=cluster_id,
                    strategy_id=strategy_ids[index % len(strategy_ids)],
                    strategy_family=family,
                    score=score,
                    entry_low=base_price,
                    entry_high=base_price + 0.7,
                    stop=base_price - 1.2,
                    target=base_price + 2.8,
                    confidence=min(0.99, 0.72 + (index * 0.005)),
                    confluence_score=compute_confluence_score(
                        daily_regime_valid=True,
                        trend_signal=index % 5 != 4,
                        momentum_signal=index % 6 != 5,
                        volume_confirmation=index % 4 != 3,
                        entry_zone_proximity=max(0.4, 1 - index * 0.01),
                    ),
                    expected_r=2.05 + (0.02 * (index % 4)),
                    created_at=now - timedelta(minutes=index * 10),
                    expires_at=now + timedelta(hours=self.settings.setup_expiration_hours),
                )
            )

        active_setups = quality_gate(
            raw_setups,
            top_percent=self.settings.quality_gate_percentile,
            min_keep=self.settings.quality_gate_min_keep,
            min_expected_r=self.settings.setup_min_expected_r,
            min_confluence_score=self.settings.setup_min_confluence_score,
        )
        self.setups = {setup.id: self._enrich_setup(setup) for setup in active_setups}
        self._record_setup_created_events(list(self.setups.values()))

        existing_position = PortfolioPosition(
            id="pos-1",
            symbol="KCHOL",
            sector="holding",
            status=PositionStatus.OPEN,
            entry_price=210.0,
            stop_price=202.0,
            target_price=228.0,
            quantity=25,
            last_price=214.0,
            opened_at=now - timedelta(days=4),
            entry_reason="Holding kumesinde trend ve geri cekilme sinyalleri birlikte guclu kaldigi icin acilmis ornek paper pozisyon.",
            adjusted_entry_price=210.0,
            adjusted_stop_price=202.0,
            adjusted_target_price=228.0,
        )
        self.positions[existing_position.id] = existing_position
        self._backfill_position_metadata()
        self._record_position_entered_event(position=existing_position, occurred_at=existing_position.opened_at)

        self.backtest_trades = {
            "strat-trend-bank": [
                TradeRecord(
                    strategy_id="strat-trend-bank",
                    symbol="AKBNK",
                    entered_at=now - timedelta(days=90),
                    exited_at=now - timedelta(days=86),
                    return_pct=0.041,
                    r_multiple=2.2,
                ),
                TradeRecord(
                    strategy_id="strat-trend-bank",
                    symbol="YKBNK",
                    entered_at=now - timedelta(days=80),
                    exited_at=now - timedelta(days=76),
                    return_pct=0.027,
                    r_multiple=1.5,
                ),
            ],
            "strat-trend-energy": [
                TradeRecord(
                    strategy_id="strat-trend-energy",
                    symbol="TUPRS",
                    entered_at=now - timedelta(days=70),
                    exited_at=now - timedelta(days=64),
                    return_pct=0.063,
                    r_multiple=2.8,
                )
            ],
        }

    def _load_real_symbol_metadata(self) -> None:
        if self.market_data_provider is None:
            return
        try:
            fetched = self.market_data_provider.fetch_sectors(as_of=date.today())
        except Exception:
            return
        merged = dict(self.symbol_sectors)
        merged.update({symbol: sector for symbol, sector in fetched.items() if sector != "unknown"})
        for symbol in self.market_data_provider.fetch_symbols():
            merged.setdefault(symbol, fetched.get(symbol, "unknown"))
        self.symbol_sectors = merged

    def refresh_research_data(
        self,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict[str, object]:
        if self.market_data_provider is None:
            raise ValueError("Gercek veri saglayicisi tanimli degil.")

        result = build_real_research_state(
            provider=self.market_data_provider,
            settings=self.settings,
            progress_callback=progress_callback,
        )
        self._apply_research_result(result)
        paper_summary = {
            "paper_opened": 0,
            "paper_closed": 0,
            "open_position_count": len(
                [position for position in self.positions.values() if position.status == PositionStatus.OPEN]
            ),
        }
        if self.settings.auto_paper_trading_enabled:
            paper_summary = self._run_auto_paper_trading_cycle(
                now=datetime.now(UTC),
                progress_callback=progress_callback,
            )
        self._persist_research_state()
        self._persist_runtime_state()
        self._emit_store_progress(
            progress_callback,
            100,
            "Veri ve paper portfoy guncellemesi tamamlandi.",
        )
        return {
            "status": "ok",
            "cached_at": self.research_cached_at.isoformat() if self.research_cached_at else None,
            "symbol_count": len(self.symbol_sectors),
            "cluster_count": len(self.clusters),
            "strategy_count": len(self.strategies),
            "trade_count": sum(len(trades) for trades in self.backtest_trades.values()),
            **paper_summary,
        }

    def list_available_symbols(self) -> list[str]:
        if self.market_data_provider is not None:
            return self.market_data_provider.fetch_symbols()
        symbols = set(self.symbol_sectors) | set(self.bars_by_symbol)
        symbols.update(position.symbol for position in self.positions.values())
        return sorted(symbols)

    def get_market_symbol_chart(
        self,
        symbol: str,
        *,
        lookback_days: int | None = None,
    ) -> dict[str, object] | None:
        normalized_symbol = symbol.upper()
        if normalized_symbol not in set(self.list_available_symbols()):
            return None
        if any(
            position.status == PositionStatus.OPEN and position.symbol == normalized_symbol
            for position in self.positions.values()
        ):
            self._refresh_open_positions_if_due()

        bars = self._get_symbol_daily_bars(
            normalized_symbol,
            lookback_days=lookback_days or self.settings.market_chart_lookback_days,
        )
        if not bars:
            return None

        markers: list[dict[str, object]] = []
        price_lines: list[dict[str, object]] = []
        hidden_overlays = 0

        for position in self.positions.values():
            if position.status != PositionStatus.OPEN or position.symbol != normalized_symbol:
                continue
            position_view = self._build_position_view(position)
            if bool(position_view["is_degraded"]):
                hidden_overlays += 1
                continue
            markers.append(
                build_price_marker(
                    timestamp=position.opened_at,
                    text=f"Giris {float(position_view['entry_price']):.2f}",
                    color="#0d8a76",
                    shape="arrowUp",
                    position="belowBar",
                )
            )
            price_lines.extend(
                [
                    build_price_line(
                        value=float(position_view["stop_price"]),
                        title=f"Stop {float(position_view['stop_price']):.2f}",
                        color="#b33c2b",
                    ),
                    build_price_line(
                        value=float(position_view["target_price"]),
                        title=f"Hedef {float(position_view['target_price']):.2f}",
                        color="#b57a18",
                    ),
                ]
            )

        chart = sanitize_chart_payload(
            build_candlestick_chart(
                symbol=normalized_symbol,
                title=f"{normalized_symbol} Gunluk Grafik",
                subtitle="Gercek BIST gunluk mumlar, onbellekten hizli yuklenir ve sadece eksik veri guncellenir",
                bars=bars,
                markers=markers,
                price_lines=price_lines,
            )
        )
        chart["data_source"] = "Yahoo Finance (.IS) + disk onbellek"
        chart["sector"] = self.symbol_sectors.get(normalized_symbol, "unknown")
        chart["bar_count"] = len(bars)
        chart["cached_at"] = self.research_cached_at.isoformat() if self.research_cached_at else None
        chart["filtered_position_overlay_count"] = hidden_overlays
        if hidden_overlays:
            chart["is_degraded"] = True
            chart["degraded_reasons"] = list(
                dict.fromkeys([*chart.get("degraded_reasons", []), "degraded_position_overlays_hidden"])
            )
        return chart

    def get_dashboard_overview(self) -> DashboardOverview:
        self._refresh_open_positions_if_due()
        open_positions = [
            position
            for position in self.positions.values()
            if position.status == PositionStatus.OPEN
            and is_finite_number(position.last_price)
            and position.quantity > 0
        ]
        total_value = self.cash_balance + sum(position.last_price * position.quantity for position in open_positions)
        return DashboardOverview(
            total_value=round(total_value, 2),
            simulated_return_pct=round(((total_value - self.initial_cash) / self.initial_cash) * 100, 2),
            active_ideas=len(
                [
                    setup
                    for setup in self.setups.values()
                    if setup.status in {SetupStatus.ACTIVE, SetupStatus.APPROVED_PENDING_ENTRY}
                ]
            ),
            open_positions=len(open_positions),
        )

    def list_top_setup_views(self, *, limit: int = 3) -> list[dict[str, object]]:
        now = datetime.now(UTC)
        return [self._build_setup_view(setup, now=now) for setup in self.list_top_setups(limit=limit)]

    def get_setup_view(self, setup_id: str) -> dict[str, object] | None:
        setup = self.get_setup(setup_id)
        if setup is None:
            return None
        return self._build_setup_view(setup, now=datetime.now(UTC))

    def get_position_view(self, position_id: str) -> dict[str, object] | None:
        position = self.get_position(position_id)
        if position is None:
            return None
        return self._build_position_view(position)

    def list_position_views(self) -> list[dict[str, object]]:
        self._refresh_open_positions_if_due()
        return [self._build_position_view(position) for position in self.positions.values()]

    def get_lifecycle_events(self, *, limit: int = 20) -> list[dict[str, object]]:
        ordered = sorted(self.lifecycle_events, key=lambda event: event.occurred_at, reverse=True)
        return [build_lifecycle_event_view(event) for event in ordered[:limit]]

    def _build_setup_view(
        self,
        setup: SetupCandidate,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        enriched = self._enrich_setup(setup)
        strategy = self.strategies.get(
            enriched.strategy_id,
            StrategyDefinition(
                id=enriched.strategy_id,
                name=enriched.strategy_id,
                family=enriched.strategy_family,
                trend_indicator="trend",
                momentum_indicator="momentum",
                volume_indicator="hacim",
            ),
        )
        cluster = self.clusters.get(enriched.cluster_id)
        cluster_label = enriched.cluster_id
        if cluster is not None:
            cluster_label = f"{cluster.sector} / {cluster.vol_bucket}"
        return build_setup_view(
            setup=enriched,
            strategy_name=strategy.name,
            strategy_family_label=self._family_label(enriched.strategy_family),
            sector=self.symbol_sectors.get(enriched.symbol, "unknown"),
            cluster_label=cluster_label,
            trend_indicator=strategy.trend_indicator or "trend",
            momentum_indicator=strategy.momentum_indicator or "momentum",
            volume_indicator=strategy.volume_indicator or "hacim",
            now=now,
        )

    def _build_position_view(self, position: PortfolioPosition) -> dict[str, object]:
        related_setup = self._resolve_related_setup_for_position(position)
        self._hydrate_position_entry_context(position, related_setup=related_setup)
        base_thesis = (
            related_setup.thesis
            if related_setup is not None and related_setup.thesis
            else f"{position.symbol} icin paper-trading pozisyonu {position.sector} grubunda izleniyor."
        )
        view = build_position_view(position=position, base_thesis=base_thesis)
        position.entry_reason = str(view["entry_reason"])
        if view["success_probability"] is not None:
            position.success_probability = float(view["success_probability"])
        if position.expected_r_at_entry is None and view["expected_r_at_entry"] is not None:
            position.expected_r_at_entry = float(view["expected_r_at_entry"])
        return view

    def _resolve_related_setup_for_position(
        self,
        position: PortfolioPosition,
    ) -> SetupCandidate | None:
        if position.source_setup_id is not None:
            related_setup = self.setups.get(position.source_setup_id)
            if related_setup is not None:
                return self._enrich_setup(related_setup)
        return self._find_related_setup_for_symbol(position.symbol)

    def _hydrate_position_entry_context(
        self,
        position: PortfolioPosition,
        related_setup: SetupCandidate | None = None,
    ) -> None:
        if related_setup is None:
            related_setup = self._resolve_related_setup_for_position(position)
        if related_setup is not None and position.source_setup_id is None:
            position.source_setup_id = related_setup.id
        if position.initial_stop_price is None:
            position.initial_stop_price = (
                related_setup.stop
                if related_setup is not None and is_finite_number(related_setup.stop)
                else position.stop_price
            )
        if position.initial_target_price is None:
            position.initial_target_price = (
                related_setup.target
                if related_setup is not None and is_finite_number(related_setup.target)
                else position.target_price
            )
        if position.expected_r_at_entry is None:
            if related_setup is not None and is_finite_number(related_setup.expected_r):
                position.expected_r_at_entry = float(related_setup.expected_r)
            else:
                position.expected_r_at_entry = compute_expected_r(
                    entry_price=position.entry_price,
                    stop_price=position.initial_stop_price,
                    target_price=position.initial_target_price,
                )
        if position.confidence_at_entry is None:
            if related_setup is not None:
                position.confidence_at_entry = normalize_probability(related_setup.confidence)
            else:
                position.confidence_at_entry = normalize_probability(position.success_probability)
        if position.success_probability is None:
            position.success_probability = position.confidence_at_entry

    def _record_lifecycle_event(
        self,
        *,
        event_type: LifecycleEventType,
        occurred_at: datetime,
        symbol: str | None = None,
        setup_id: str | None = None,
        position_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self._event_sequence += 1
        event = LifecycleEvent(
            id=f"event-{self._event_sequence}",
            event_type=event_type,
            occurred_at=occurred_at,
            symbol=symbol,
            setup_id=setup_id,
            position_id=position_id,
            details=dict(details or {}),
        )
        self.lifecycle_events.append(event)
        if len(self.lifecycle_events) > MAX_LIFECYCLE_EVENTS:
            self.lifecycle_events = self.lifecycle_events[-MAX_LIFECYCLE_EVENTS:]

    def _record_setup_created_events(self, setups: list[SetupCandidate]) -> None:
        for setup in setups:
            self._record_lifecycle_event(
                event_type=LifecycleEventType.SETUP_CREATED,
                occurred_at=setup.created_at,
                symbol=setup.symbol,
                setup_id=setup.id,
                details={
                    "symbol": setup.symbol,
                    "strategy_id": setup.strategy_id,
                    "score": setup.score,
                },
            )

    def _record_setup_transition(
        self,
        previous: SetupCandidate,
        updated: SetupCandidate,
        *,
        occurred_at: datetime,
    ) -> None:
        if previous.status == updated.status:
            return
        if updated.status == SetupStatus.APPROVED_PENDING_ENTRY:
            event_type = LifecycleEventType.SETUP_APPROVED
        elif updated.status == SetupStatus.EXPIRED:
            event_type = LifecycleEventType.SETUP_EXPIRED
        elif updated.status == SetupStatus.INVALIDATED:
            event_type = LifecycleEventType.SETUP_INVALIDATED
        else:
            return
        details: dict[str, object] = {"symbol": updated.symbol}
        if updated.invalidated_reason:
            details["reason"] = updated.invalidated_reason
        self._record_lifecycle_event(
            event_type=event_type,
            occurred_at=occurred_at,
            symbol=updated.symbol,
            setup_id=updated.id,
            details=details,
        )

    def _record_position_entered_event(
        self,
        *,
        position: PortfolioPosition,
        occurred_at: datetime,
    ) -> None:
        self._record_lifecycle_event(
            event_type=LifecycleEventType.POSITION_ENTERED,
            occurred_at=occurred_at,
            symbol=position.symbol,
            setup_id=position.source_setup_id,
            position_id=position.id,
            details={
                "symbol": position.symbol,
                "entry_price": position.entry_price,
                "stop_price": position.stop_price,
                "target_price": position.target_price,
                "quantity": position.quantity,
            },
        )

    def _record_position_stop_event(
        self,
        *,
        position: PortfolioPosition,
        occurred_at: datetime,
        from_stop: float,
        to_stop: float,
        moved_to_plus_1r: bool,
    ) -> None:
        self._record_lifecycle_event(
            event_type=(
                LifecycleEventType.STOP_MOVED_TO_PLUS_1R
                if moved_to_plus_1r
                else LifecycleEventType.STOP_MOVED_TO_BREAKEVEN
            ),
            occurred_at=occurred_at,
            symbol=position.symbol,
            setup_id=position.source_setup_id,
            position_id=position.id,
            details={
                "symbol": position.symbol,
                "from_stop": from_stop,
                "to_stop": to_stop,
            },
        )

    def _record_position_closed_event(
        self,
        *,
        position: PortfolioPosition,
        occurred_at: datetime,
        exit_price: float,
        close_reason: str,
    ) -> None:
        self._record_lifecycle_event(
            event_type=LifecycleEventType.POSITION_CLOSED,
            occurred_at=occurred_at,
            symbol=position.symbol,
            setup_id=position.source_setup_id,
            position_id=position.id,
            details={
                "symbol": position.symbol,
                "exit_price": exit_price,
                "quantity": position.quantity,
                "close_reason": close_reason,
            },
        )

    def list_top_setups(self, *, limit: int = 3) -> list[SetupCandidate]:
        self._ensure_real_research_data()
        active = [
            setup
            for setup in self.setups.values()
            if setup.status in {SetupStatus.ACTIVE, SetupStatus.APPROVED_PENDING_ENTRY}
        ]
        active.sort(key=lambda setup: setup.score, reverse=True)
        return active[:limit]

    def get_setup(self, setup_id: str) -> SetupCandidate | None:
        return self.setups.get(setup_id)

    def approve_setup(self, setup_id: str) -> SetupCandidate:
        setup = self._require_setup(setup_id)
        now = datetime.now(UTC)
        updated = approve_setup(setup, now=now)
        self.setups[setup_id] = updated
        self._record_setup_transition(setup, updated, occurred_at=now)
        self._persist_runtime_state()
        return updated

    def reject_setup(self, setup_id: str) -> SetupCandidate:
        setup = self._require_setup(setup_id)
        updated = reject_setup(setup)
        self.setups[setup_id] = updated
        self._persist_runtime_state()
        return updated

    def create_manual_position(
        self,
        *,
        setup_id: str,
        fill_price: float,
        filled_at: datetime,
        quantity: int | None,
    ) -> PortfolioPosition:
        setup = self._require_setup(setup_id)
        refreshed = refresh_setup_status(
            setup,
            now=filled_at,
            daily_regime_valid=True,
            entry_distance_atr=0.0,
            stop_logic_intact=True,
        )
        if refreshed.status != setup.status:
            self.setups[setup_id] = refreshed
            self._record_setup_transition(setup, refreshed, occurred_at=filled_at)
            self._persist_runtime_state()
        if refreshed.status != SetupStatus.APPROVED_PENDING_ENTRY:
            raise ValueError("Setup is no longer eligible for manual entry.")
        setup = refreshed
        resolved_fill_price, _, _ = validate_long_trade_values(
            entry_price=require_finite_number("fill_price", fill_price),
            stop_price=setup.stop,
            target_price=setup.target,
        )

        portfolio_equity = self.get_dashboard_overview().total_value
        resolved_quantity = (
            require_positive_int("quantity", quantity)
            if quantity is not None
            else calculate_position_size(
                portfolio_equity=portfolio_equity,
                entry_price=resolved_fill_price,
                stop_price=setup.stop,
                risk_per_trade=self.settings.risk_per_trade,
            )
        )

        proposed_position = ProposedPosition(
            symbol=setup.symbol,
            sector=self.symbol_sectors.get(setup.symbol, "unknown"),
            entry_price=resolved_fill_price,
            stop_price=setup.stop,
            last_price=resolved_fill_price,
            quantity=resolved_quantity,
        )
        evaluation = evaluate_position_constraints(
            existing_positions=[position for position in self.positions.values() if position.status == PositionStatus.OPEN],
            proposed_position=proposed_position,
            portfolio_equity=portfolio_equity,
            correlation_map=self.correlation_map,
            max_sector_positions=self.settings.max_sector_positions,
            max_sector_exposure=self.settings.max_sector_exposure,
            max_correlation=self.settings.max_correlation,
            max_total_portfolio_risk=self.settings.max_total_portfolio_risk,
        )
        if not evaluation.accepted:
            raise ValueError(f"Position rejected: {', '.join(evaluation.violations)}")

        position_id = f"pos-{len(self.positions) + 1}"
        position = PortfolioPosition(
            id=position_id,
            symbol=setup.symbol,
            sector=proposed_position.sector,
            status=PositionStatus.OPEN,
            entry_price=resolved_fill_price,
            stop_price=setup.stop,
            target_price=setup.target,
            quantity=resolved_quantity,
            last_price=resolved_fill_price,
            opened_at=filled_at,
            success_probability=normalize_probability(setup.confidence),
            adjusted_entry_price=resolved_fill_price,
            adjusted_stop_price=setup.stop,
            adjusted_target_price=setup.target,
            source_setup_id=setup.id,
            initial_stop_price=setup.stop,
            initial_target_price=setup.target,
            expected_r_at_entry=setup.expected_r,
            confidence_at_entry=normalize_probability(setup.confidence),
        )
        self._hydrate_position_entry_context(position, related_setup=setup)
        position.entry_reason = self._build_position_view(position)["entry_reason"]
        self.positions[position.id] = position
        setup.status = SetupStatus.ENTERED
        self.cash_balance -= resolved_fill_price * resolved_quantity
        self._record_position_entered_event(position=position, occurred_at=filled_at)
        self._persist_runtime_state()
        return position

    def update_position(
        self,
        position_id: str,
        *,
        stop_price: float | None = None,
        target_price: float | None = None,
        last_price: float | None = None,
        status: str | None = None,
        closed_at: datetime | None = None,
    ) -> PortfolioPosition:
        position = self.positions[position_id]
        current_stop = stop_price if stop_price is not None else position.stop_price
        current_target = target_price if target_price is not None else position.target_price
        validate_long_trade_values(
            entry_price=position.entry_price,
            stop_price=current_stop,
            target_price=current_target,
        )
        if stop_price is not None:
            position.stop_price = require_finite_number("stop_price", stop_price)
            position.adjusted_stop_price = position.stop_price
        if target_price is not None:
            position.target_price = require_finite_number("target_price", target_price)
            position.adjusted_target_price = position.target_price
        if last_price is not None:
            position.last_price = require_finite_number("last_price", last_price)
        if status is not None and status not in {PositionStatus.OPEN.value, PositionStatus.CLOSED.value}:
            raise ValueError("Unsupported position status.")
        if status == PositionStatus.CLOSED.value:
            if not is_finite_number(position.last_price):
                raise ValueError("last_price must be finite when closing a position.")
            position.status = PositionStatus.CLOSED
            position.closed_at = closed_at or datetime.now(UTC)
            self.cash_balance += position.last_price * position.quantity
            self._record_position_closed_event(
                position=position,
                occurred_at=position.closed_at,
                exit_price=position.last_price,
                close_reason="manual_close",
            )
        self._build_position_view(position)
        self._persist_runtime_state()
        return position

    def _run_auto_paper_trading_cycle(
        self,
        *,
        now: datetime,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict[str, int]:
        self._emit_store_progress(
            progress_callback,
            97,
            "Paper portfoyde acik islemler guncelleniyor...",
        )
        closed_count = self._refresh_open_positions(now=now)
        self._emit_store_progress(
            progress_callback,
            99,
            "Paper portfoy icin yeni islemler aciliyor...",
        )
        opened_count = self._auto_enter_setups(now=now)
        open_count = len(
            [position for position in self.positions.values() if position.status == PositionStatus.OPEN]
        )
        return {
            "paper_opened": opened_count,
            "paper_closed": closed_count,
            "open_position_count": open_count,
        }

    def _refresh_open_positions(self, *, now: datetime) -> int:
        closed_count = 0
        for position in list(self.positions.values()):
            if position.status != PositionStatus.OPEN:
                continue
            self._hydrate_position_entry_context(position)

            bars = self.bars_by_symbol.get(position.symbol, [])
            if not bars:
                bars = self._fetch_bars(
                    position.symbol,
                    timeframe=self.settings.research_timeframe,
                    start=now - timedelta(days=60),
                    end=now,
                    force_refresh=True,
                )
            if not bars:
                continue

            latest_bar = bars[-1]
            if not (
                is_finite_number(latest_bar.close)
                and is_finite_number(latest_bar.low)
                and is_finite_number(latest_bar.high)
            ):
                continue
            position.last_price = latest_bar.close
            initial_stop = (
                position.initial_stop_price
                if position.initial_stop_price is not None
                else position.stop_price
            )
            risk_per_share = max(position.entry_price - initial_stop, 0.0)

            if risk_per_share > 0:
                old_stop = position.stop_price
                moved_to_plus_1r = False
                moved_to_breakeven = False
                if latest_bar.close >= position.entry_price + (2 * risk_per_share):
                    position.stop_price = max(
                        position.stop_price,
                        position.entry_price + risk_per_share,
                    )
                    moved_to_plus_1r = position.stop_price > old_stop
                elif latest_bar.close >= position.entry_price + risk_per_share:
                    position.stop_price = max(position.stop_price, position.entry_price)
                    moved_to_breakeven = position.stop_price > old_stop
                position.adjusted_stop_price = position.stop_price
                if moved_to_plus_1r:
                    self._record_position_stop_event(
                        position=position,
                        occurred_at=latest_bar.timestamp,
                        from_stop=old_stop,
                        to_stop=position.stop_price,
                        moved_to_plus_1r=True,
                    )
                elif moved_to_breakeven:
                    self._record_position_stop_event(
                        position=position,
                        occurred_at=latest_bar.timestamp,
                        from_stop=old_stop,
                        to_stop=position.stop_price,
                        moved_to_plus_1r=False,
                    )

            if latest_bar.low <= position.stop_price:
                self._close_simulated_position(
                    position=position,
                    exit_price=position.stop_price,
                    closed_at=latest_bar.timestamp,
                    close_reason="stop_hit",
                )
                closed_count += 1
                continue

            keep_open = self._should_keep_open_after_soft_limit(
                position=position,
                as_of=now,
                force_fresh=True,
            )
            if latest_bar.high >= position.target_price and not keep_open:
                self._close_simulated_position(
                    position=position,
                    exit_price=position.target_price,
                    closed_at=latest_bar.timestamp,
                    close_reason="target_hit",
                )
                closed_count += 1
                continue

            if not keep_open:
                self._close_simulated_position(
                    position=position,
                    exit_price=latest_bar.close,
                    closed_at=latest_bar.timestamp,
                    close_reason="soft_limit_close",
                )
                closed_count += 1

        return closed_count

    def _auto_enter_setups(self, *, now: datetime) -> int:
        opened_count = 0
        open_symbols = {
            position.symbol
            for position in self.positions.values()
            if position.status == PositionStatus.OPEN
        }
        candidates = [
            setup
            for setup in self.setups.values()
            if setup.status == SetupStatus.ACTIVE
        ]
        candidates.sort(key=lambda setup: setup.score, reverse=True)

        for setup in candidates:
            if opened_count >= self.settings.auto_paper_max_new_positions_per_refresh:
                break
            refreshed = refresh_setup_status(
                setup,
                now=now,
                daily_regime_valid=True,
                entry_distance_atr=0.0,
                stop_logic_intact=True,
            )
            if refreshed.status != setup.status:
                self.setups[setup.id] = refreshed
                self._record_setup_transition(setup, refreshed, occurred_at=now)
                setup = refreshed
            if setup.status != SetupStatus.ACTIVE:
                continue
            if setup.symbol in open_symbols:
                continue

            bars = self.bars_by_symbol.get(setup.symbol, [])
            if not bars:
                bars = self._fetch_bars(
                    setup.symbol,
                    timeframe=self.settings.research_timeframe,
                    start=now - timedelta(days=60),
                    end=now,
                )
            if not bars:
                continue
            latest_bar = bars[-1]
            if not is_finite_number(latest_bar.close):
                continue
            fill_price = min(max(float(latest_bar.close), setup.entry_low), setup.entry_high)
            try:
                fill_price, _, _ = validate_long_trade_values(
                    entry_price=fill_price,
                    stop_price=setup.stop,
                    target_price=setup.target,
                )
            except ValueError:
                continue

            portfolio_equity = self.get_dashboard_overview().total_value
            desired_quantity = calculate_position_size(
                portfolio_equity=portfolio_equity,
                entry_price=fill_price,
                stop_price=setup.stop,
                risk_per_trade=self.settings.risk_per_trade,
            )
            affordable_quantity = int(self.cash_balance // fill_price) if fill_price > 0 else 0
            resolved_quantity = min(desired_quantity, affordable_quantity)
            if resolved_quantity < 1:
                continue

            proposed_position = ProposedPosition(
                symbol=setup.symbol,
                sector=self.symbol_sectors.get(setup.symbol, "unknown"),
                entry_price=fill_price,
                stop_price=setup.stop,
                last_price=latest_bar.close,
                quantity=resolved_quantity,
            )
            evaluation = evaluate_position_constraints(
                existing_positions=[
                    position
                    for position in self.positions.values()
                    if position.status == PositionStatus.OPEN
                ],
                proposed_position=proposed_position,
                portfolio_equity=portfolio_equity,
                correlation_map=self.correlation_map,
                max_sector_positions=self.settings.max_sector_positions,
                max_sector_exposure=self.settings.max_sector_exposure,
                max_correlation=self.settings.max_correlation,
                max_total_portfolio_risk=self.settings.max_total_portfolio_risk,
            )
            if not evaluation.accepted:
                continue

            position = PortfolioPosition(
                id=f"pos-{len(self.positions) + 1}",
                symbol=setup.symbol,
                sector=proposed_position.sector,
                status=PositionStatus.OPEN,
                entry_price=fill_price,
                stop_price=setup.stop,
                target_price=setup.target,
                quantity=resolved_quantity,
                last_price=latest_bar.close,
                opened_at=latest_bar.timestamp,
                adjusted_entry_price=fill_price,
                adjusted_stop_price=setup.stop,
                adjusted_target_price=setup.target,
                source_setup_id=setup.id,
                initial_stop_price=setup.stop,
                initial_target_price=setup.target,
                expected_r_at_entry=setup.expected_r,
                confidence_at_entry=normalize_probability(setup.confidence),
                success_probability=normalize_probability(setup.confidence),
            )
            self._hydrate_position_entry_context(position, related_setup=setup)
            position.entry_reason = self._build_position_view(position)["entry_reason"]
            self.positions[position.id] = position
            self.cash_balance -= fill_price * resolved_quantity
            setup.status = SetupStatus.ENTERED
            self._record_position_entered_event(position=position, occurred_at=latest_bar.timestamp)
            open_symbols.add(setup.symbol)
            opened_count += 1

        return opened_count

    def _should_keep_open_after_soft_limit(
        self,
        *,
        position: PortfolioPosition,
        as_of: datetime,
        force_fresh: bool = False,
    ) -> bool:
        holding_days = (as_of.date() - position.opened_at.date()).days
        if holding_days <= self.settings.paper_trade_soft_limit_days:
            return True

        daily_bars = self._get_symbol_daily_bars(
            position.symbol,
            lookback_days=180,
            force_refresh=force_fresh,
        )
        if len(daily_bars) < 60:
            return False

        indicators = compute_indicators(daily_bars)
        daily_close = daily_bars[-1].close
        daily_ema20 = indicators.ema20[-1]
        daily_ema50 = indicators.ema50[-1]
        if daily_ema20 is None or daily_ema50 is None:
            return False

        return should_keep_position_open(
            opened_at=position.opened_at,
            as_of=as_of,
            daily_close=daily_close,
            daily_ema20=daily_ema20,
            daily_ema50=daily_ema50,
            soft_limit_days=self.settings.paper_trade_soft_limit_days,
        )

    def _close_simulated_position(
        self,
        *,
        position: PortfolioPosition,
        exit_price: float,
        closed_at: datetime,
        close_reason: str,
    ) -> None:
        position.last_price = exit_price
        position.status = PositionStatus.CLOSED
        position.closed_at = closed_at
        self.cash_balance += exit_price * position.quantity
        self._record_position_closed_event(
            position=position,
            occurred_at=closed_at,
            exit_price=exit_price,
            close_reason=close_reason,
        )

    def _enrich_setup(self, setup: SetupCandidate) -> SetupCandidate:
        strategy_score = self.strategy_scores.get(setup.strategy_id)
        if strategy_score is not None:
            setup.wf_window_count = strategy_score.walk_forward_window_count
            setup.wf_win_rate = round(strategy_score.win_rate * 100, 2)
            setup.wf_total_return_pct = round(strategy_score.total_return * 100, 2)
        if not setup.thesis:
            setup.thesis = self._build_setup_thesis(setup)
        return setup

    def _build_setup_thesis(self, setup: SetupCandidate) -> str:
        strategy = self.strategies.get(setup.strategy_id)
        cluster = self.clusters.get(setup.cluster_id)
        family_label = self._family_label(setup.strategy_family)
        cluster_label = setup.cluster_id
        if cluster is not None:
            cluster_label = f"{cluster.sector} / {cluster.vol_bucket}"
        return build_setup_thesis(
            family_label=family_label,
            cluster_label=cluster_label,
            trend_indicator=(strategy.trend_indicator if strategy else "trend"),
            momentum_indicator=(strategy.momentum_indicator if strategy else "momentum"),
            volume_indicator=(strategy.volume_indicator if strategy else "hacim"),
            confluence_score=setup.confluence_score,
            score=setup.score,
            expected_r=setup.expected_r,
            wf_window_count=setup.wf_window_count,
            wf_win_rate=setup.wf_win_rate,
            wf_total_return_pct=setup.wf_total_return_pct,
        )

    def _build_position_entry_reason(
        self,
        *,
        setup: SetupCandidate,
        fill_price: float,
    ) -> str:
        return build_position_entry_reason(
            base_thesis=self._build_setup_thesis(setup),
            entry_price=fill_price,
            stop_price=setup.stop,
            target_price=setup.target,
            expected_r_at_entry=setup.expected_r,
            confidence_at_entry=normalize_probability(setup.confidence),
        )

    @staticmethod
    def _normalize_probability(probability: float | None) -> float | None:
        return normalize_probability(probability)

    @staticmethod
    def _format_probability_pct(probability: float | None) -> float | None:
        return format_probability_pct(probability)

    def _find_related_setup_for_symbol(self, symbol: str) -> SetupCandidate | None:
        normalized_symbol = symbol.upper()
        for preferred_status in (
            SetupStatus.ENTERED,
            SetupStatus.APPROVED_PENDING_ENTRY,
            SetupStatus.ACTIVE,
        ):
            for setup in self.setups.values():
                if setup.symbol == normalized_symbol and setup.status == preferred_status:
                    return self._enrich_setup(setup)
        return None

    def _resolve_position_success_probability(
        self,
        *,
        setup: SetupCandidate | None = None,
        symbol: str | None = None,
    ) -> float | None:
        related_setup = setup
        if related_setup is None and symbol is not None:
            related_setup = self._find_related_setup_for_symbol(symbol)
        if related_setup is None:
            return None
        return self._normalize_probability(related_setup.confidence)

    def _backfill_position_metadata(self) -> None:
        if not self.positions:
            return
        for position in self.positions.values():
            related_setup = self._resolve_related_setup_for_position(position)
            self._hydrate_position_entry_context(position, related_setup=related_setup)
            view = self._build_position_view(position)
            position.entry_reason = str(view["entry_reason"])

    def _bootstrap_paper_portfolio(self) -> None:
        if not self.settings.auto_paper_trading_enabled:
            return
        has_open_positions = any(
            position.status == PositionStatus.OPEN for position in self.positions.values()
        )
        if not self.setups and not has_open_positions:
            return
        self._run_auto_paper_trading_cycle(now=datetime.now(UTC))
        self._persist_runtime_state()

    def _refresh_open_positions_if_due(self, *, force: bool = False) -> None:
        if self.market_data_provider is None:
            return
        if not any(position.status == PositionStatus.OPEN for position in self.positions.values()):
            return
        now = datetime.now(UTC)
        if not force and self._last_live_positions_refresh_at is not None:
            elapsed = (now - self._last_live_positions_refresh_at).total_seconds()
            if elapsed < self.settings.live_position_refresh_interval_seconds:
                return
        self._refresh_open_positions(now=now)
        self._persist_runtime_state()
        self._last_live_positions_refresh_at = now

    def get_position(self, position_id: str) -> PortfolioPosition | None:
        return self.positions.get(position_id)

    def list_positions(self) -> list[PortfolioPosition]:
        self._refresh_open_positions_if_due()
        return list(self.positions.values())

    def list_backtest_clusters(self) -> list[dict[str, object]]:
        self._ensure_real_research_data()
        cluster_rows: list[dict[str, object]] = []
        for cluster_id, cluster in self.clusters.items():
            strategies = [
                score
                for score in self._visible_strategy_scores()
                if score.cluster_id == cluster_id
            ]
            if not strategies:
                continue
            cluster_rows.append(
                {
                    **asdict(cluster),
                    "active_strategy_ids": [
                        strategy_id
                        for strategy_id in self.cluster_active_strategy_ids.get(cluster_id, [])
                        if self._is_visible_strategy(strategy_id)
                    ],
                    "backtest_mode": "walk_forward",
                    "strategy_count": len(strategies),
                    "walk_forward_window_count": max(
                        (score.walk_forward_window_count for score in strategies),
                        default=0,
                    ),
                }
            )
        return cluster_rows

    def list_cluster_strategies(self, cluster_id: str) -> list[StrategyScore]:
        self._ensure_real_research_data()
        scores = [
            score
            for score in self._visible_strategy_scores()
            if score.cluster_id == cluster_id
        ]
        scores.sort(key=lambda score: score.composite_score, reverse=True)
        return scores

    def list_strategy_trades(self, strategy_id: str) -> list[TradeRecord]:
        self._ensure_real_research_data()
        if not self._is_visible_strategy(strategy_id):
            return []
        return self.backtest_trades.get(strategy_id, [])

    def apply_corporate_action(self, action: CorporateAction) -> float:
        cash_delta = 0.0
        for position_id, position in list(self.positions.items()):
            if position.status != PositionStatus.OPEN:
                continue
            adjusted_position, position_cash_delta = adjust_position_for_corporate_action(position, action)
            self.positions[position_id] = adjusted_position
            cash_delta += position_cash_delta
        self.cash_balance += cash_delta
        self._persist_runtime_state()
        return cash_delta

    def get_strategy_insights(self, *, limit: int = 3) -> dict[str, list[dict[str, object]]]:
        self._ensure_real_research_data()
        scores = self._visible_strategy_scores()
        ordered = sorted(scores, key=lambda score: score.composite_score, reverse=True)

        def enrich(score: StrategyScore) -> dict[str, object]:
            strategy = self.strategies[score.strategy_id]
            return {
                "strategy_id": score.strategy_id,
                "name": strategy.name,
                "family": self._family_label(strategy.family),
                "cluster_id": score.cluster_id,
                "composite_score": round(score.composite_score, 4),
                "return": round(score.total_return * 100, 2),
                "win_rate": round(score.win_rate * 100, 2),
                "profit_factor": round(score.profit_factor, 2),
                "max_drawdown": round(score.max_drawdown * 100, 2),
                "trade_count": score.trade_count,
                "walk_forward_window_count": score.walk_forward_window_count,
                "backtest_mode": score.backtest_mode,
            }

        return {
            "best": [enrich(score) for score in ordered[:limit]],
            "worst": [enrich(score) for score in ordered[-limit:]][::-1],
        }

    def get_dashboard_page_data(self) -> dict[str, object]:
        self._refresh_open_positions_if_due()
        market_watchlist_views = self.get_market_watchlist()
        available_symbols = self.list_available_symbols()
        top_setup_views = self.list_top_setup_views()
        top_setups = [setup for setup in top_setup_views if not bool(setup["is_degraded"])]
        position_views = self.list_position_views()
        open_positions = [
            position
            for position in position_views
            if position["status"] == PositionStatus.OPEN.value
        ]
        visible_positions = [position for position in open_positions if not bool(position["is_degraded"])]
        pending_setup_views = [
            self._build_setup_view(setup, now=datetime.now(UTC))
            for setup in self.setups.values()
            if setup.status == SetupStatus.APPROVED_PENDING_ENTRY
        ]
        visible_pending_setups = [
            setup for setup in pending_setup_views if not bool(setup["is_degraded"])
        ]
        visible_market_watchlist = [
            row for row in market_watchlist_views if not bool(row["is_degraded"])
        ]
        featured_symbol = (
            (visible_market_watchlist[0]["symbol"] if visible_market_watchlist else None)
            or (visible_positions[0]["symbol"] if visible_positions else None)
            or (available_symbols[0] if available_symbols else None)
        )
        return {
            "overview": asdict(self.get_dashboard_overview()),
            "market_watchlist": visible_market_watchlist,
            "market_watchlist_hidden_count": len(market_watchlist_views) - len(visible_market_watchlist),
            "top_setups": top_setups,
            "top_setups_hidden_count": len(top_setup_views) - len(top_setups),
            "positions": visible_positions,
            "positions_hidden_count": len(open_positions) - len(visible_positions),
            "pending_setups": visible_pending_setups,
            "pending_setups_hidden_count": len(pending_setup_views) - len(visible_pending_setups),
            "live_trade_charts": self.get_live_trade_charts(),
            "available_symbols": available_symbols,
            "featured_symbol": featured_symbol,
            "research_cached_at": self.research_cached_at.isoformat() if self.research_cached_at else None,
            "strategy_insights": self.get_strategy_insights(),
            "recent_lifecycle_events": self.get_lifecycle_events(limit=8),
        }

    def get_backtest_page_data(self) -> dict[str, object]:
        self._ensure_real_research_data()
        symbol_limit = self.settings.backtest_symbol_summary_limit or None
        backtest_symbols = self.list_backtest_symbols(limit=symbol_limit)
        clusters = self.list_backtest_clusters()
        ranked_clusters = []
        for cluster in clusters:
            strategies = self.list_cluster_strategies(str(cluster["id"]))
            avg_score = fmean(score.composite_score for score in strategies) if strategies else 0.0
            ranked_clusters.append(
                {
                    **cluster,
                    "avg_score": round(avg_score, 4),
                    "top_strategies": [
                        {
                            "strategy_id": score.strategy_id,
                            "name": self.strategies[score.strategy_id].name,
                            "family": self._family_label(score.family),
                            "composite_score": round(score.composite_score, 4),
                            "return": round(score.total_return * 100, 2),
                            "win_rate": round(score.win_rate * 100, 2),
                            "profit_factor": round(score.profit_factor, 2),
                            "max_drawdown": round(score.max_drawdown * 100, 2),
                            "walk_forward_window_count": score.walk_forward_window_count,
                            "backtest_mode": score.backtest_mode,
                        }
                        for score in strategies[:3]
                    ],
                }
            )
        ranked_clusters.sort(key=lambda cluster: cluster["avg_score"], reverse=True)

        recent_trades = []
        for strategy_id, trades in self.backtest_trades.items():
            if not self._is_visible_strategy(strategy_id):
                continue
            for trade in trades:
                recent_trades.append(
                    {
                        **asdict(trade),
                        "strategy_name": self.strategies[strategy_id].name,
                    }
                )
        recent_trades.sort(key=lambda trade: trade["exited_at"], reverse=True)

        return {
            "clusters": ranked_clusters,
            "top_backtest_symbols": backtest_symbols,
            "available_backtest_symbols": [item["symbol"] for item in self.list_backtest_symbols()],
            "featured_backtest_symbol": backtest_symbols[0]["symbol"] if backtest_symbols else None,
            "strategy_insights": self.get_strategy_insights(limit=5),
            "recent_trades": recent_trades[:8],
            "trade_charts": self.get_backtest_trade_charts(limit=self.settings.backtest_trade_chart_limit),
            "research_cached_at": self.research_cached_at.isoformat() if self.research_cached_at else None,
        }

    def get_live_trade_charts(self) -> list[dict[str, object]]:
        self._refresh_open_positions_if_due()
        charts: list[dict[str, object]] = []
        for position in self.positions.values():
            if position.status != PositionStatus.OPEN:
                continue
            position_view = self._build_position_view(position)
            if bool(position_view["is_degraded"]):
                continue
            bars = self._fetch_live_trade_bars(position)
            if not bars:
                continue
            chart = sanitize_chart_payload(
                build_candlestick_chart(
                    symbol=position.symbol,
                    title=f"{position.symbol} Canli Islem",
                    subtitle="Gercek BIST 1 saatlik mumlar, giris, canli fiyat, stop ve hedef",
                    bars=bars,
                    markers=[
                        build_price_marker(
                            timestamp=position.opened_at,
                            text=f"Entry {float(position_view['entry_price']):.2f}",
                            color="#0d8a76",
                            shape="arrowUp",
                            position="belowBar",
                        ),
                        build_price_marker(
                            timestamp=bars[-1].timestamp,
                            text=f"Live {bars[-1].close:.2f}",
                            color="#1d2430",
                            shape="circle",
                            position="aboveBar",
                        ),
                    ],
                    price_lines=[
                        build_price_line(
                            value=float(position_view["stop_price"]),
                            title=f"Stop {float(position_view['stop_price']):.2f}",
                            color="#b33c2b",
                        ),
                        build_price_line(
                            value=float(position_view["target_price"]),
                            title=f"Target {float(position_view['target_price']):.2f}",
                            color="#b57a18",
                        ),
                    ],
                )
            )
            if bool(chart["is_degraded"]) or not chart["candles"]:
                continue
            chart["data_source"] = "Yahoo Finance (.IS)"
            chart["quantity"] = position.quantity
            chart["opened_at"] = position.opened_at.isoformat()
            chart["entry_reason"] = position_view["entry_reason"]
            charts.append(chart)
        return charts

    def get_market_watchlist(self, *, limit: int = 6) -> list[dict[str, object]]:
        if self.market_data_provider is None:
            return []

        rows: list[dict[str, object]] = []
        end = datetime.now(UTC)
        start = end - timedelta(days=5)
        for symbol in self.market_data_provider.fetch_symbols()[:limit]:
            bars = self._fetch_bars(symbol, timeframe="1d", start=start, end=end)
            if len(bars) < 2:
                continue
            last_bar = bars[-1]
            prev_close = bars[-2].close
            rows.append(
                build_watchlist_row_view(
                    symbol=symbol,
                    sector=self.symbol_sectors.get(symbol, "unknown"),
                    close=round(last_bar.close, 2) if is_finite_number(last_bar.close) else last_bar.close,
                    change_pct=(
                        round(((last_bar.close - prev_close) / prev_close) * 100, 2)
                        if is_finite_number(prev_close) and float(prev_close) > 0 and is_finite_number(last_bar.close)
                        else None
                    ),
                    high=round(last_bar.high, 2) if is_finite_number(last_bar.high) else last_bar.high,
                    low=round(last_bar.low, 2) if is_finite_number(last_bar.low) else last_bar.low,
                    volume=last_bar.volume,
                )
            )
        return rows

    def get_backtest_trade_charts(self, *, limit: int = 3) -> list[dict[str, object]]:
        self._ensure_real_research_data()
        trade_cards: list[dict[str, object]] = []
        for summary in self.list_backtest_symbols(limit=limit):
            chart = self.get_backtest_symbol_chart(summary["symbol"])
            if chart is None:
                continue
            trade_cards.append(chart)
            if len(trade_cards) >= limit:
                break
        return trade_cards[:limit]

    def list_backtest_symbols(self, *, limit: int | None = None) -> list[dict[str, object]]:
        self._ensure_real_research_data()
        trades_by_symbol: dict[str, list[TradeRecord]] = {}
        strategies_by_symbol: dict[str, set[str]] = {}
        for strategy_id, trades in self.backtest_trades.items():
            if not self._is_visible_strategy(strategy_id):
                continue
            for trade in trades:
                trades_by_symbol.setdefault(trade.symbol, []).append(trade)
                strategies_by_symbol.setdefault(trade.symbol, set()).add(strategy_id)

        rows: list[dict[str, object]] = []
        for symbol, trades in trades_by_symbol.items():
            if not trades:
                continue
            returns = [trade.return_pct for trade in trades]
            wins = [value for value in returns if value > 0]
            compounded = 1.0
            for value in returns:
                compounded *= 1 + value
            rows.append(
                {
                    "symbol": symbol,
                    "sector": self.symbol_sectors.get(symbol, "unknown"),
                    "backtest_mode": "walk_forward",
                    "trade_count": len(trades),
                    "strategy_count": len(strategies_by_symbol.get(symbol, set())),
                    "total_return_pct": round((compounded - 1) * 100, 2),
                    "win_rate": round((len(wins) / len(returns)) * 100, 2) if returns else 0.0,
                    "avg_r": round(
                        fmean(trade.r_multiple for trade in trades if trade.r_multiple is not None),
                        2,
                    ) if trades else 0.0,
                    "walk_forward_window_count": max(
                        (
                            self.strategy_scores[strategy_id].walk_forward_window_count
                            for strategy_id in strategies_by_symbol.get(symbol, set())
                            if strategy_id in self.strategy_scores
                        ),
                        default=0,
                    ),
                    "last_trade_at": max(trade.exited_at for trade in trades).isoformat(),
                }
            )

        rows.sort(
            key=lambda item: (
                float(item["total_return_pct"]),
                int(item["trade_count"]),
                float(item["avg_r"]),
            ),
            reverse=True,
        )
        return rows[:limit] if limit is not None else rows

    def get_backtest_symbol_chart(self, symbol: str) -> dict[str, object] | None:
        self._ensure_real_research_data()
        normalized_symbol = symbol.upper()
        symbol_trades: list[TradeRecord] = []
        strategy_names: set[str] = set()
        for strategy_id, trades in self.backtest_trades.items():
            if not self._is_visible_strategy(strategy_id):
                continue
            for trade in trades:
                if trade.symbol != normalized_symbol:
                    continue
                symbol_trades.append(trade)
                strategy_names.add(self.strategies.get(strategy_id, StrategyDefinition(
                    id=strategy_id,
                    name=strategy_id,
                    family=StrategyFamily.TREND_FOLLOWING,
                    trend_indicator="",
                    momentum_indicator="",
                    volume_indicator="",
                )).name)

        if not symbol_trades:
            return None

        symbol_trades.sort(key=lambda trade: trade.entered_at)
        bars = self.bars_by_symbol.get(normalized_symbol, [])
        if not bars:
            bars = self._get_symbol_daily_bars(normalized_symbol, lookback_days=self.settings.market_chart_lookback_days)
        if not bars:
            return None

        markers: list[dict[str, object]] = []
        for trade in symbol_trades:
            entry_bar = self._nearest_bar(bars, trade.entered_at)
            exit_bar = self._nearest_bar(bars, trade.exited_at)
            entry_price = trade.entry_price if trade.entry_price is not None else entry_bar.close
            exit_price = trade.exit_price if trade.exit_price is not None else exit_bar.close
            markers.append(
                build_price_marker(
                    timestamp=trade.entered_at,
                    text=f"Giris {entry_price:.2f}",
                    color="#0d8a76",
                    shape="arrowUp",
                    position="belowBar",
                )
            )
            markers.append(
                build_price_marker(
                    timestamp=trade.exited_at,
                    text=f"Cikis {exit_price:.2f}",
                    color="#d26d3d",
                    shape="arrowDown",
                    position="aboveBar",
                )
            )

        if not markers:
            return None

        compounded = 1.0
        for trade in symbol_trades:
            compounded *= 1 + trade.return_pct

        chart = sanitize_chart_payload(
            build_candlestick_chart(
            symbol=normalized_symbol,
            title=f"{normalized_symbol} Walk-Forward OOS Backtest",
            subtitle=f"Secilen hisse icin test pencerelerinden olusan OOS giris ve cikislar ({bars[-1].timeframe.upper()})",
            bars=bars[-self._backtest_chart_bar_limit(bars[-1].timeframe):],
            markers=markers,
            )
        )
        chart["data_source"] = f"Yahoo Finance (.IS) · {bars[-1].timeframe.upper()}"
        chart["backtest_mode"] = "walk_forward"
        chart["return_pct"] = round((compounded - 1) * 100, 2)
        chart["r_multiple"] = round(
            fmean(trade.r_multiple for trade in symbol_trades if trade.r_multiple is not None),
            2,
        ) if symbol_trades else 0.0
        chart["trade_count"] = len(symbol_trades)
        chart["strategy_count"] = len(strategy_names)
        chart["walk_forward_window_count"] = max(
            (
                self.strategy_scores[strategy_id].walk_forward_window_count
                for strategy_id in self.backtest_trades
                if strategy_id in self.strategy_scores
                and any(trade.symbol == normalized_symbol for trade in self.backtest_trades.get(strategy_id, []))
            ),
            default=0,
        )
        chart["strategy_name"] = ", ".join(sorted(strategy_names)[:3])
        chart["entered_at"] = symbol_trades[0].entered_at.isoformat()
        chart["exited_at"] = symbol_trades[-1].exited_at.isoformat()
        return chart

    def _fetch_live_trade_bars(self, position: PortfolioPosition) -> list[PriceBar]:
        end = datetime.now(UTC)
        start = end - timedelta(days=self.settings.chart_live_lookback_days)
        bars = self._fetch_bars(
            position.symbol,
            timeframe="1h",
            start=start,
            end=end,
            force_refresh=True,
        )
        if bars:
            return bars[-120:]
        return []

    def _fetch_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        force_refresh: bool = False,
    ) -> list[PriceBar]:
        if self.market_data_provider is None or not self.settings.enable_real_market_data:
            return []
        bars = self.market_data_provider.fetch_bars(
            symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            force_refresh=force_refresh,
        )
        if timeframe == "1d" and bars:
            self.bars_by_symbol[symbol] = bars
        return bars

    def _get_symbol_daily_bars(
        self,
        symbol: str,
        *,
        lookback_days: int,
        force_refresh: bool = False,
    ) -> list[PriceBar]:
        end = datetime.now(UTC)
        start = end - timedelta(days=lookback_days)
        bars = self._fetch_bars(
            symbol,
            timeframe="1d",
            start=start,
            end=end,
            force_refresh=force_refresh,
        )
        if bars:
            return bars
        return self.bars_by_symbol.get(symbol, [])

    @staticmethod
    def _nearest_bar(bars: list[PriceBar], target: datetime) -> PriceBar:
        target_ts = target.timestamp()
        return min(bars, key=lambda bar: abs(bar.timestamp.timestamp() - target_ts))

    def _ensure_real_research_data(self) -> None:
        if self._real_data_loaded or self._real_data_attempted:
            return
        self._real_data_attempted = True

    @staticmethod
    def _emit_store_progress(
        callback: Callable[[int, str], None] | None,
        percent: int,
        message: str,
    ) -> None:
        if callback is None:
            return
        callback(max(0, min(100, int(percent))), message)

    @staticmethod
    def _most_traded_symbol(trades: list[TradeRecord]) -> str:
        counts: dict[str, int] = {}
        for trade in trades:
            counts[trade.symbol] = counts.get(trade.symbol, 0) + 1
        return max(counts, key=counts.get)

    def _visible_strategy_scores(self) -> list[StrategyScore]:
        return [
            score
            for score in self.strategy_scores.values()
            if not is_garbage_strategy(score)
        ]

    def _is_visible_strategy(self, strategy_id: str) -> bool:
        score = self.strategy_scores.get(strategy_id)
        return score is not None and not is_garbage_strategy(score)

    @staticmethod
    def _family_label(family: StrategyFamily) -> str:
        labels = {
            StrategyFamily.TREND_FOLLOWING: "Trend Takibi",
            StrategyFamily.PULLBACK_MEAN_REVERSION: "Geri Cekilme",
            StrategyFamily.BREAKOUT_VOLUME: "Hacimli Kirilim",
        }
        return labels[family]

    @staticmethod
    def _backtest_chart_bar_limit(timeframe: str) -> int:
        if timeframe == "4h":
            return 1200
        if timeframe == "1h":
            return 1600
        return 520

    def _require_setup(self, setup_id: str) -> SetupCandidate:
        setup = self.get_setup(setup_id)
        if setup is None:
            raise KeyError(f"Unknown setup: {setup_id}")
        return setup

    def _apply_research_result(self, result) -> None:
        previous_setup_ids = set(self.setups)
        self.symbol_sectors = result.symbol_sectors
        self.bars_by_symbol = result.bars_by_symbol
        self.clusters = result.clusters
        self.strategies = result.strategies
        self.strategy_scores = result.strategy_scores
        self.cluster_active_strategy_ids = result.cluster_active_strategy_ids
        self.backtest_trades = result.backtest_trades
        self.setups = {setup.id: self._enrich_setup(setup) for setup in result.setups}
        self._record_setup_created_events(
            [setup for setup_id, setup in self.setups.items() if setup_id not in previous_setup_ids]
        )
        self._backfill_position_metadata()
        self.research_cached_at = datetime.now(UTC)
        self._real_data_loaded = True
        self._real_data_attempted = True

    def _load_cached_runtime_state(self) -> None:
        if self.disk_cache is None:
            return
        payload = self.disk_cache.load_runtime_state()
        if not payload:
            return

        self.cash_balance = float(payload.get("cash_balance", self.cash_balance))
        positions: dict[str, PortfolioPosition] = {}
        for item in payload.get("positions", []):
            try:
                position = PortfolioPosition(
                    id=str(item["id"]),
                    symbol=str(item["symbol"]),
                    sector=str(item["sector"]),
                    status=PositionStatus(str(item["status"])),
                    entry_price=float(item["entry_price"]),
                    stop_price=float(item["stop_price"]),
                    target_price=float(item["target_price"]),
                    quantity=int(item["quantity"]),
                    last_price=float(item["last_price"]),
                    opened_at=datetime.fromisoformat(item["opened_at"]),
                    entry_reason=str(item.get("entry_reason", "")),
                    success_probability=(
                        self._normalize_probability(item["success_probability"])
                        if item.get("success_probability") is not None
                        else None
                    ),
                    closed_at=datetime.fromisoformat(item["closed_at"]) if item.get("closed_at") else None,
                    adjustment_factor=float(item.get("adjustment_factor", 1.0)),
                    adjusted_entry_price=float(item["adjusted_entry_price"]) if item.get("adjusted_entry_price") is not None else None,
                    adjusted_stop_price=float(item["adjusted_stop_price"]) if item.get("adjusted_stop_price") is not None else None,
                    adjusted_target_price=float(item["adjusted_target_price"]) if item.get("adjusted_target_price") is not None else None,
                    last_corporate_action_at=(
                        datetime.fromisoformat(item["last_corporate_action_at"])
                        if item.get("last_corporate_action_at")
                        else None
                    ),
                    source_setup_id=str(item["source_setup_id"]) if item.get("source_setup_id") else None,
                    initial_stop_price=float(item["initial_stop_price"]) if item.get("initial_stop_price") is not None else None,
                    initial_target_price=float(item["initial_target_price"]) if item.get("initial_target_price") is not None else None,
                    expected_r_at_entry=float(item["expected_r_at_entry"]) if item.get("expected_r_at_entry") is not None else None,
                    confidence_at_entry=(
                        normalize_probability(item["confidence_at_entry"])
                        if item.get("confidence_at_entry") is not None
                        else None
                    ),
                )
            except (KeyError, TypeError, ValueError):
                continue
            positions[position.id] = position
        self.positions = positions
        lifecycle_events: list[LifecycleEvent] = []
        for item in payload.get("lifecycle_events", []):
            try:
                lifecycle_events.append(
                    LifecycleEvent(
                        id=str(item["id"]),
                        event_type=LifecycleEventType(str(item["event_type"])),
                        occurred_at=datetime.fromisoformat(item["occurred_at"]),
                        symbol=str(item["symbol"]) if item.get("symbol") else None,
                        setup_id=str(item["setup_id"]) if item.get("setup_id") else None,
                        position_id=str(item["position_id"]) if item.get("position_id") else None,
                        details=dict(item.get("details", {})),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self.lifecycle_events = lifecycle_events[-MAX_LIFECYCLE_EVENTS:]
        self._event_sequence = len(self.lifecycle_events)

    def _persist_runtime_state(self) -> None:
        if self.disk_cache is None:
            return
        payload = {
            "cash_balance": self.cash_balance,
            "positions": [
                {
                    "id": position.id,
                    "symbol": position.symbol,
                    "sector": position.sector,
                    "status": position.status.value,
                    "entry_price": position.entry_price,
                    "stop_price": position.stop_price,
                    "target_price": position.target_price,
                    "quantity": position.quantity,
                    "last_price": position.last_price,
                    "opened_at": position.opened_at.isoformat(),
                    "entry_reason": position.entry_reason,
                    "success_probability": position.success_probability,
                    "closed_at": position.closed_at.isoformat() if position.closed_at else None,
                    "adjustment_factor": position.adjustment_factor,
                    "adjusted_entry_price": position.adjusted_entry_price,
                    "adjusted_stop_price": position.adjusted_stop_price,
                    "adjusted_target_price": position.adjusted_target_price,
                    "last_corporate_action_at": (
                        position.last_corporate_action_at.isoformat()
                        if position.last_corporate_action_at
                        else None
                    ),
                    "source_setup_id": position.source_setup_id,
                    "initial_stop_price": position.initial_stop_price,
                    "initial_target_price": position.initial_target_price,
                    "expected_r_at_entry": position.expected_r_at_entry,
                    "confidence_at_entry": position.confidence_at_entry,
                }
                for position in self.positions.values()
            ],
            "lifecycle_events": [
                {
                    "id": event.id,
                    "event_type": event.event_type.value,
                    "occurred_at": event.occurred_at.isoformat(),
                    "symbol": event.symbol,
                    "setup_id": event.setup_id,
                    "position_id": event.position_id,
                    "details": event.details,
                }
                for event in self.lifecycle_events[-MAX_LIFECYCLE_EVENTS:]
            ],
        }
        self.disk_cache.save_runtime_state(payload)

    def _load_cached_research_state(self) -> None:
        if self.disk_cache is None:
            return
        payload = self.disk_cache.load_research_state()
        if not payload:
            return
        if payload.get("research_state_schema_version") != RESEARCH_STATE_SCHEMA_VERSION:
            return
        if payload.get("research_timeframe") != self.settings.research_timeframe:
            return

        self.research_cached_at = (
            datetime.fromisoformat(payload["cached_at"])
            if payload.get("cached_at")
            else None
        )
        self.symbol_sectors = {
            str(symbol): str(sector)
            for symbol, sector in payload.get("symbol_sectors", {}).items()
        }
        self.clusters = {
            item["id"]: ClusterDefinition(
                id=str(item["id"]),
                sector=str(item["sector"]),
                vol_bucket=str(item["vol_bucket"]),
                symbol_count=int(item["symbol_count"]),
                fallback_mode=ClusterFallbackMode(str(item["fallback_mode"])),
                as_of=date.fromisoformat(item["as_of"]),
                members=[str(member) for member in item.get("members", [])],
            )
            for item in payload.get("clusters", [])
        }
        self.strategies = {
            item["id"]: StrategyDefinition(
                id=str(item["id"]),
                name=str(item["name"]),
                family=StrategyFamily(str(item["family"])),
                trend_indicator=str(item["trend_indicator"]),
                momentum_indicator=str(item["momentum_indicator"]),
                volume_indicator=str(item["volume_indicator"]),
                params=dict(item.get("params", {})),
                is_active=bool(item.get("is_active", True)),
            )
            for item in payload.get("strategies", [])
        }
        self.strategy_scores = {
            item["strategy_id"]: StrategyScore(
                strategy_id=str(item["strategy_id"]),
                cluster_id=str(item["cluster_id"]),
                as_of=date.fromisoformat(item["as_of"]),
                family=StrategyFamily(str(item["family"])),
                total_return=float(item["total_return"]),
                win_rate=float(item["win_rate"]),
                profit_factor=float(item["profit_factor"]),
                max_drawdown=float(item["max_drawdown"]),
                trade_count=int(item["trade_count"]),
                avg_trade_return=float(item["avg_trade_return"]),
                estimated_round_trip_cost=float(item["estimated_round_trip_cost"]),
                oos_window_trade_counts=[int(value) for value in item.get("oos_window_trade_counts", [])],
                oos_returns=[float(value) for value in item.get("oos_returns", [])],
                walk_forward_window_count=int(item.get("walk_forward_window_count", 0)),
                backtest_mode=str(item.get("backtest_mode", "walk_forward")),
                normalized_return=float(item.get("normalized_return", 0.0)),
                normalized_win_rate=float(item.get("normalized_win_rate", 0.0)),
                normalized_profit_factor=float(item.get("normalized_profit_factor", 0.0)),
                normalized_max_drawdown=float(item.get("normalized_max_drawdown", 0.0)),
                composite_score=float(item.get("composite_score", 0.0)),
            )
            for item in payload.get("strategy_scores", [])
        }
        self.cluster_active_strategy_ids = {
            str(cluster_id): [str(strategy_id) for strategy_id in strategy_ids]
            for cluster_id, strategy_ids in payload.get("cluster_active_strategy_ids", {}).items()
        }
        self.backtest_trades = {
            str(strategy_id): [
                TradeRecord(
                    strategy_id=str(item["strategy_id"]),
                    symbol=str(item["symbol"]),
                    entered_at=datetime.fromisoformat(item["entered_at"]),
                    exited_at=datetime.fromisoformat(item["exited_at"]),
                    return_pct=float(item["return_pct"]),
                    r_multiple=float(item["r_multiple"]),
                    entry_price=float(item["entry_price"]) if item.get("entry_price") is not None else None,
                    exit_price=float(item["exit_price"]) if item.get("exit_price") is not None else None,
                )
                for item in items
            ]
            for strategy_id, items in payload.get("backtest_trades", {}).items()
        }
        self.setups = {
            str(item["id"]): SetupCandidate(
                id=str(item["id"]),
                symbol=str(item["symbol"]),
                cluster_id=str(item["cluster_id"]),
                strategy_id=str(item["strategy_id"]),
                strategy_family=StrategyFamily(str(item["strategy_family"])),
                score=float(item["score"]),
                entry_low=float(item["entry_low"]),
                entry_high=float(item["entry_high"]),
                stop=float(item["stop"]),
                target=float(item["target"]),
                confidence=float(item["confidence"]),
                confluence_score=float(item["confluence_score"]),
                expected_r=float(item["expected_r"]),
                created_at=datetime.fromisoformat(item["created_at"]),
                expires_at=datetime.fromisoformat(item["expires_at"]),
                wf_window_count=int(item.get("wf_window_count", 0)),
                wf_win_rate=float(item.get("wf_win_rate", 0.0)),
                wf_total_return_pct=float(item.get("wf_total_return_pct", 0.0)),
                thesis=str(item.get("thesis", "")),
                status=SetupStatus(str(item.get("status", SetupStatus.ACTIVE.value))),
                invalidated_reason=str(item["invalidated_reason"]) if item.get("invalidated_reason") else None,
            )
            for item in payload.get("setups", [])
        }
        self.setups = {setup_id: self._enrich_setup(setup) for setup_id, setup in self.setups.items()}
        self._backfill_position_metadata()
        self._real_data_loaded = bool(self.strategy_scores)

    def _persist_research_state(self) -> None:
        if self.disk_cache is None:
            return
        payload = {
            "research_state_schema_version": RESEARCH_STATE_SCHEMA_VERSION,
            "cached_at": self.research_cached_at.isoformat() if self.research_cached_at else None,
            "research_timeframe": self.settings.research_timeframe,
            "symbol_sectors": self.symbol_sectors,
            "clusters": [
                {
                    "id": cluster.id,
                    "sector": cluster.sector,
                    "vol_bucket": cluster.vol_bucket,
                    "symbol_count": cluster.symbol_count,
                    "fallback_mode": cluster.fallback_mode.value,
                    "as_of": cluster.as_of.isoformat(),
                    "members": cluster.members,
                }
                for cluster in self.clusters.values()
            ],
            "strategies": [
                {
                    "id": strategy.id,
                    "name": strategy.name,
                    "family": strategy.family.value,
                    "trend_indicator": strategy.trend_indicator,
                    "momentum_indicator": strategy.momentum_indicator,
                    "volume_indicator": strategy.volume_indicator,
                    "params": strategy.params,
                    "is_active": strategy.is_active,
                }
                for strategy in self.strategies.values()
            ],
            "strategy_scores": [
                {
                    "strategy_id": score.strategy_id,
                    "cluster_id": score.cluster_id,
                    "as_of": score.as_of.isoformat(),
                    "family": score.family.value,
                    "total_return": score.total_return,
                    "win_rate": score.win_rate,
                    "profit_factor": score.profit_factor,
                    "max_drawdown": score.max_drawdown,
                    "trade_count": score.trade_count,
                    "avg_trade_return": score.avg_trade_return,
                    "estimated_round_trip_cost": score.estimated_round_trip_cost,
                    "oos_window_trade_counts": score.oos_window_trade_counts,
                    "oos_returns": score.oos_returns,
                    "walk_forward_window_count": score.walk_forward_window_count,
                    "backtest_mode": score.backtest_mode,
                    "normalized_return": score.normalized_return,
                    "normalized_win_rate": score.normalized_win_rate,
                    "normalized_profit_factor": score.normalized_profit_factor,
                    "normalized_max_drawdown": score.normalized_max_drawdown,
                    "composite_score": score.composite_score,
                }
                for score in self.strategy_scores.values()
            ],
            "cluster_active_strategy_ids": self.cluster_active_strategy_ids,
            "backtest_trades": {
                strategy_id: [
                    {
                        "strategy_id": trade.strategy_id,
                        "symbol": trade.symbol,
                        "entered_at": trade.entered_at.isoformat(),
                        "exited_at": trade.exited_at.isoformat(),
                        "return_pct": trade.return_pct,
                        "r_multiple": trade.r_multiple,
                        "entry_price": trade.entry_price,
                        "exit_price": trade.exit_price,
                    }
                    for trade in trades
                ]
                for strategy_id, trades in self.backtest_trades.items()
            },
            "setups": [
                {
                    "id": setup.id,
                    "symbol": setup.symbol,
                    "cluster_id": setup.cluster_id,
                    "strategy_id": setup.strategy_id,
                    "strategy_family": setup.strategy_family.value,
                    "score": setup.score,
                    "entry_low": setup.entry_low,
                    "entry_high": setup.entry_high,
                    "stop": setup.stop,
                    "target": setup.target,
                    "confidence": setup.confidence,
                    "confluence_score": setup.confluence_score,
                    "expected_r": setup.expected_r,
                    "created_at": setup.created_at.isoformat(),
                    "expires_at": setup.expires_at.isoformat(),
                    "wf_window_count": setup.wf_window_count,
                    "wf_win_rate": setup.wf_win_rate,
                    "wf_total_return_pct": setup.wf_total_return_pct,
                    "thesis": setup.thesis,
                    "status": setup.status.value,
                    "invalidated_reason": setup.invalidated_reason,
                }
                for setup in self.setups.values()
            ],
        }
        self.disk_cache.save_research_state(payload)
