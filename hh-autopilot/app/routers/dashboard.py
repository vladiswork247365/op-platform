"""Server-rendered admin panel pages (data hydrated client-side via /api)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _page(request: Request, name: str, title: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request, name, {"title": title, "active": name}
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _page(request, "dashboard.html", "Обзор")


@router.get("/vacancies", response_class=HTMLResponse)
def vacancies_page(request: Request) -> HTMLResponse:
    return _page(request, "vacancies.html", "Вакансии")


@router.get("/vacancy/{vacancy_id}", response_class=HTMLResponse)
def vacancy_page(request: Request, vacancy_id: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "vacancy_detail.html",
        {"title": "Вакансия", "active": "vacancies", "vacancy_id": vacancy_id},
    )


@router.get("/attention", response_class=HTMLResponse)
def attention_page(request: Request) -> HTMLResponse:
    return _page(request, "attention.html", "Требует внимания")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    return _page(request, "settings.html", "Настройки")


@router.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request) -> HTMLResponse:
    return _page(request, "runs.html", "Циклы")
