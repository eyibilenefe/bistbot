CREATE TABLE symbols (
    symbol TEXT PRIMARY KEY,
    sector TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE bars_1d (
    symbol TEXT NOT NULL REFERENCES symbols(symbol),
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC(18,6) NOT NULL,
    high NUMERIC(18,6) NOT NULL,
    low NUMERIC(18,6) NOT NULL,
    close NUMERIC(18,6) NOT NULL,
    volume NUMERIC(20,4) NOT NULL,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE bars_1h (
    symbol TEXT NOT NULL REFERENCES symbols(symbol),
    ts TIMESTAMPTZ NOT NULL,
    open NUMERIC(18,6) NOT NULL,
    high NUMERIC(18,6) NOT NULL,
    low NUMERIC(18,6) NOT NULL,
    close NUMERIC(18,6) NOT NULL,
    volume NUMERIC(20,4) NOT NULL,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE strategy_definitions (
    strategy_id TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    trend_indicator TEXT NOT NULL,
    momentum_indicator TEXT NOT NULL,
    volume_indicator TEXT NOT NULL,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE strategy_runs (
    strategy_id TEXT NOT NULL REFERENCES strategy_definitions(strategy_id),
    cluster_id TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    train_start DATE NOT NULL,
    train_end DATE NOT NULL,
    test_start DATE NOT NULL,
    test_end DATE NOT NULL,
    metrics JSONB NOT NULL,
    PRIMARY KEY (strategy_id, cluster_id, as_of_date)
) PARTITION BY RANGE (as_of_date);

CREATE TABLE strategy_scores (
    strategy_id TEXT NOT NULL REFERENCES strategy_definitions(strategy_id),
    cluster_id TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    family TEXT NOT NULL,
    total_return NUMERIC(12,6) NOT NULL,
    win_rate NUMERIC(12,6) NOT NULL,
    profit_factor NUMERIC(12,6) NOT NULL,
    max_drawdown NUMERIC(12,6) NOT NULL,
    trade_count INTEGER NOT NULL,
    avg_trade_return NUMERIC(12,6) NOT NULL,
    estimated_round_trip_cost NUMERIC(12,6) NOT NULL,
    normalized_return NUMERIC(12,6) NOT NULL,
    normalized_win_rate NUMERIC(12,6) NOT NULL,
    normalized_profit_factor NUMERIC(12,6) NOT NULL,
    normalized_max_drawdown NUMERIC(12,6) NOT NULL,
    composite_score NUMERIC(12,6) NOT NULL,
    PRIMARY KEY (strategy_id, cluster_id, as_of_date)
) PARTITION BY RANGE (as_of_date);

CREATE TABLE strategy_runs_2026_03 PARTITION OF strategy_runs
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE TABLE strategy_scores_2026_03 PARTITION OF strategy_scores
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE INDEX idx_strategy_runs_cluster_as_of
    ON strategy_runs (cluster_id, as_of_date DESC);
CREATE INDEX idx_strategy_runs_strategy_as_of
    ON strategy_runs (strategy_id, as_of_date DESC);
CREATE INDEX idx_strategy_scores_cluster_as_of
    ON strategy_scores (cluster_id, as_of_date DESC);
CREATE INDEX idx_strategy_scores_strategy_as_of
    ON strategy_scores (strategy_id, as_of_date DESC);

CREATE TABLE setup_candidates (
    setup_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES symbols(symbol),
    cluster_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL REFERENCES strategy_definitions(strategy_id),
    status TEXT NOT NULL,
    score NUMERIC(12,6) NOT NULL,
    confluence_score NUMERIC(12,6) NOT NULL,
    expected_r NUMERIC(12,6) NOT NULL,
    entry_low NUMERIC(18,6) NOT NULL,
    entry_high NUMERIC(18,6) NOT NULL,
    stop_price NUMERIC(18,6) NOT NULL,
    target_price NUMERIC(18,6) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    invalidated_reason TEXT
);

CREATE TABLE portfolio_positions (
    position_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES symbols(symbol),
    sector TEXT NOT NULL,
    status TEXT NOT NULL,
    entry_price NUMERIC(18,6) NOT NULL,
    stop_price NUMERIC(18,6) NOT NULL,
    target_price NUMERIC(18,6) NOT NULL,
    quantity INTEGER NOT NULL,
    last_price NUMERIC(18,6) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    adjustment_factor NUMERIC(18,6) NOT NULL DEFAULT 1.0,
    adjusted_entry_price NUMERIC(18,6),
    adjusted_stop_price NUMERIC(18,6),
    adjusted_target_price NUMERIC(18,6),
    last_corporate_action_at TIMESTAMPTZ
);

CREATE TABLE job_runs (
    job_run_id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
