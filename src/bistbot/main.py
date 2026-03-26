from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bistbot.api.routes import register_routes
from bistbot.config import get_settings
from bistbot.providers.base import MarketDataProvider
from bistbot.providers.yahoo import YahooFinanceBISTProvider
from bistbot.services.jobs import JobService
from bistbot.storage.memory import InMemoryStore
from bistbot.web.routes import register_web_routes


def create_app(
    *,
    market_data_provider: MarketDataProvider | None = None,
    seed_demo_data: bool = False,
) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="BISTBot",
        version="0.1.0",
        description="Gercek BIST verisiyle calisan otomatik paper-trading odakli arastirma platformu.",
    )
    app.state.settings = settings
    provider = market_data_provider
    if provider is None and settings.enable_real_market_data:
        provider = YahooFinanceBISTProvider(cache_dir=settings.cache_dir)
    app.state.store = InMemoryStore(
        settings,
        market_data_provider=provider,
        seed_demo_data=seed_demo_data,
    )
    app.state.jobs = JobService()

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    register_web_routes(app)
    register_routes(app)
    return app


app = create_app()
