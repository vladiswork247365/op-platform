"""Панель управления видео-конвейером — FastAPI-приложение.

Труба: Telegram → панель (оркестрация по коду) → один видео-инструмент → мастер в Telegram.
Вся логика — в бэкенде. Бот тупой, инструмент сменный (adapters/).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import jobs, presets, telegram, tool

app = FastAPI(title="Content Factory Panel", version="1.0.0")

# фронт (op-front) ходит из браузера — разрешаем CORS для GET/POST/PUT
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telegram.router)
app.include_router(tool.router)
app.include_router(jobs.router)
app.include_router(presets.router)


@app.get("/health")
def health():
    return {"ok": True, "tool": settings.TOOL, "r2": settings.r2_enabled}
