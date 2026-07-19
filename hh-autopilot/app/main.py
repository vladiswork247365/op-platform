"""FastAPI application entrypoint: wiring, lifespan, routers, static, templates."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .db import init_db
from .scheduler import MANAGER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    if settings.scheduler_enabled:
        MANAGER.start()
    try:
        yield
    finally:
        MANAGER.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="HH Autopilot", version="1.0.0", lifespan=lifespan)
    app.state.templates = templates

    static_dir = BASE_DIR / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from .routers import api, dashboard, health

    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(dashboard.router)
    return app


app = create_app()
