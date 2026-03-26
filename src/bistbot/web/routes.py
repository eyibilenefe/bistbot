from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter()


def get_store(request: Request):
    return request.app.state.store


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    context = {
        "request": request,
        "page": "dashboard",
        **get_store(request).get_dashboard_page_data(),
    }
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    context = {
        "request": request,
        "page": "dashboard",
        **get_store(request).get_dashboard_page_data(),
    }
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/backtest", response_class=HTMLResponse)
def backtest(request: Request):
    context = {
        "request": request,
        "page": "backtest",
        **get_store(request).get_backtest_page_data(),
    }
    return templates.TemplateResponse(request, "backtest.html", context)


def register_web_routes(app: FastAPI) -> None:
    app.include_router(router)
