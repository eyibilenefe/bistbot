# BISTBot

BISTBot is a Python-centric research platform skeleton for manual-execution BIST swing trading workflows.

## Features

- Point-in-time cluster assignment by sector and volatility bucket
- Cluster-aware strategy scoring with rank or winsorized z-score normalization
- Dynamic trading cost model with volatility-adjusted slippage
- Setup lifecycle management with expiration and manual-entry revalidation
- Portfolio risk engine with sector, correlation, and total risk caps
- FastAPI endpoints for dashboard, setups, positions, backtests, and job runs
- Server-rendered dashboard and backtest pages at `/dashboard` and `/backtest`

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
uvicorn bistbot.main:app --reload
pytest
```

## API Surface

- `GET /api/dashboard/overview`
- `GET /api/market/symbols`
- `GET /api/market/charts/{symbol}`
- `GET /api/setups/top`
- `GET /api/setups/{setup_id}`
- `POST /api/setups/{setup_id}/approve`
- `POST /api/setups/{setup_id}/reject`
- `POST /api/positions/manual-entry`
- `PATCH /api/positions/{position_id}`
- `GET /api/positions`
- `GET /api/backtests/clusters`
- `GET /api/backtests/symbols`
- `GET /api/backtests/symbols/{symbol}`
- `GET /api/backtests/clusters/{cluster_id}/strategies`
- `GET /api/backtests/strategies/{strategy_id}/trades`
- `POST /api/jobs/{job_name}/run`
- `POST /api/cache/refresh`
- `GET /api/cache/refresh/{job_id}`
