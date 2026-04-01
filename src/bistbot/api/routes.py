from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from bistbot.api.schemas import ManualEntryRequest, PositionUpdateRequest
from bistbot.storage.base import StorageRepository

router = APIRouter(prefix="/api")


def get_store(request: Request) -> StorageRepository:
    return request.app.state.store


def get_jobs(request: Request):
    return request.app.state.jobs


@router.get("/dashboard/overview")
def dashboard_overview(request: Request):
    return jsonable_encoder(get_store(request).get_dashboard_overview())


@router.get("/market/symbols")
def list_market_symbols(request: Request):
    return jsonable_encoder(get_store(request).list_available_symbols())


@router.get("/market/charts/{symbol}")
def get_market_chart(request: Request, symbol: str):
    chart = get_store(request).get_market_symbol_chart(symbol)
    if chart is None:
        raise HTTPException(status_code=404, detail="Chart not found")
    return jsonable_encoder(chart)


@router.get("/setups/top")
def list_top_setups(request: Request):
    return jsonable_encoder(get_store(request).list_top_setup_views())


@router.get("/setups/{setup_id}")
def get_setup(request: Request, setup_id: str):
    setup = get_store(request).get_setup_view(setup_id)
    if setup is None:
        raise HTTPException(status_code=404, detail="Setup not found")
    return jsonable_encoder(setup)


@router.post("/setups/{setup_id}/approve")
def approve_setup_route(request: Request, setup_id: str):
    try:
        setup = get_store(request).approve_setup(setup_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return jsonable_encoder(setup)


@router.post("/setups/{setup_id}/reject")
def reject_setup_route(request: Request, setup_id: str):
    try:
        setup = get_store(request).reject_setup(setup_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return jsonable_encoder(setup)


@router.post("/positions/manual-entry")
def create_manual_entry(request: Request, payload: ManualEntryRequest):
    store = get_store(request)
    try:
        position = store.create_manual_position(
            setup_id=payload.setup_id,
            fill_price=payload.fill_price,
            filled_at=payload.filled_at,
            quantity=payload.quantity,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return jsonable_encoder(store.get_position_view(position.id))


@router.patch("/positions/{position_id}")
def update_position_route(request: Request, position_id: str, payload: PositionUpdateRequest):
    store = get_store(request)
    if store.get_position(position_id) is None:
        raise HTTPException(status_code=404, detail="Position not found")
    try:
        position = store.update_position(
            position_id,
            stop_price=payload.stop_price,
            target_price=payload.target_price,
            last_price=payload.last_price,
            status=payload.status,
            closed_at=payload.closed_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return jsonable_encoder(store.get_position_view(position.id))


@router.get("/positions")
def list_positions(request: Request):
    return jsonable_encoder(get_store(request).list_position_views())


@router.get("/paper-trades/history")
def list_paper_trade_history(request: Request, limit: int = 20):
    return jsonable_encoder(get_store(request).list_paper_trade_history(limit=limit))


@router.get("/paper-trades/symbols/{symbol}")
def get_paper_trade_symbol_chart_route(request: Request, symbol: str):
    chart = get_store(request).get_paper_trade_symbol_chart(symbol)
    if chart is None:
        raise HTTPException(status_code=404, detail="Paper trade symbol not found")
    return jsonable_encoder(chart)


@router.get("/events/lifecycle")
def list_lifecycle_events(request: Request, limit: int = 20):
    return jsonable_encoder(get_store(request).get_lifecycle_events(limit=limit))


@router.get("/backtests/clusters")
def list_backtest_clusters(request: Request):
    return jsonable_encoder(get_store(request).list_backtest_clusters())


@router.get("/backtests/symbols")
def list_backtest_symbols_route(request: Request):
    return jsonable_encoder(get_store(request).list_backtest_symbols())


@router.get("/backtests/symbols/{symbol}")
def get_backtest_symbol_chart_route(request: Request, symbol: str):
    chart = get_store(request).get_backtest_symbol_chart(symbol)
    if chart is None:
        raise HTTPException(status_code=404, detail="Backtest symbol not found")
    return jsonable_encoder(chart)


@router.get("/backtests/clusters/{cluster_id}/strategies")
def list_cluster_strategies_route(request: Request, cluster_id: str):
    return jsonable_encoder(get_store(request).list_cluster_strategies(cluster_id))


@router.get("/backtests/strategies/{strategy_id}/trades")
def list_strategy_trades_route(request: Request, strategy_id: str):
    return jsonable_encoder(get_store(request).list_strategy_trades(strategy_id))


@router.post("/jobs/{job_name}/run")
def run_job_route(request: Request, job_name: str):
    try:
        job = get_jobs(request).run(job_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return jsonable_encoder(job)


@router.post("/cache/refresh")
def refresh_cache_route(request: Request):
    try:
        store = get_store(request)
        result = get_jobs(request).start_refresh(
            lambda progress_callback: store.refresh_research_data(progress_callback=progress_callback)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return jsonable_encoder(result)


@router.get("/cache/refresh/{job_id}")
def get_refresh_status_route(request: Request, job_id: str):
    try:
        status = get_jobs(request).get_refresh_status(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return jsonable_encoder(status)


def register_routes(app: FastAPI) -> None:
    app.include_router(router)
