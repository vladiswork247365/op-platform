"""JSON API for the admin panel + control actions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..health import build_health
from ..models import (
    AIAnalysis,
    Application,
    AppSetting,
    AuditLog,
    Contact,
    SystemRun,
    Vacancy,
    VacancyStatus,
    WhatsAppMessage,
)
from ..runtime import effective_run_mode
from ..scheduler import CYCLE_JOB, MANAGER

router = APIRouter(prefix="/api", tags=["api"])


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _next_run() -> str | None:
    if MANAGER.scheduler:
        job = MANAGER.scheduler.get_job(CYCLE_JOB)
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    return None


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    today = _today_start()
    today_runs = db.query(SystemRun).filter(SystemRun.started_at >= today).all()

    def _sum(attr: str) -> int:
        return sum(getattr(r, attr) for r in today_runs)

    last_run = (
        db.query(SystemRun).order_by(SystemRun.started_at.desc()).first()
    )
    health = build_health(db, scheduler=MANAGER.scheduler)
    return {
        "system_status": health["status"],
        "run_mode": effective_run_mode(db, get_settings()),
        "last_check": last_run.started_at.isoformat() if last_run else None,
        "next_check": _next_run(),
        "today": {
            "found": _sum("found"),
            "new": _sum("new"),
            "analyzed": _sum("sent_to_ai"),
            "match": _sum("matched"),
            "review": _sum("review"),
            "reject": _sum("rejected"),
            "applied": _sum("applied"),
            "whatsapp": _sum("whatsapp"),
            "errors": _sum("errors"),
        },
        "queue_depth": health["queue_depth"],
        "errors_24h": health["errors_24h"],
    }


_FILTERS = {
    "today": lambda q: q.filter(Vacancy.discovered_at >= _today_start()),
    "yesterday": lambda q: q.filter(
        Vacancy.discovered_at >= _today_start() - timedelta(days=1),
        Vacancy.discovered_at < _today_start(),
    ),
    "week": lambda q: q.filter(
        Vacancy.discovered_at >= _today_start() - timedelta(days=7)
    ),
    "match": lambda q: q.filter(Vacancy.decision == "MATCH"),
    "review": lambda q: q.filter(Vacancy.decision == "REVIEW"),
    "reject": lambda q: q.filter(Vacancy.decision == "REJECT"),
    "applied": lambda q: q.filter(Vacancy.applied.is_(True)),
    "attention": lambda q: q.filter(
        Vacancy.status == VacancyStatus.NEEDS_ATTENTION.value
    ),
}


def _vacancy_row(v: Vacancy) -> dict[str, Any]:
    return {
        "id": v.id,
        "discovered_at": v.discovered_at.isoformat() if v.discovered_at else None,
        "company": v.company,
        "title": v.title,
        "score": v.score,
        "decision": v.decision,
        "applied": v.applied,
        "whatsapp": v.whatsapp_sent,
        "status": v.status,
        "url": v.url,
    }


@router.get("/vacancies")
def vacancies(
    filter: str = "week", limit: int = 100, db: Session = Depends(get_db)
) -> dict[str, Any]:
    q = db.query(Vacancy)
    if filter in _FILTERS:
        q = _FILTERS[filter](q)
    rows = q.order_by(Vacancy.discovered_at.desc()).limit(min(limit, 500)).all()
    return {"count": len(rows), "items": [_vacancy_row(v) for v in rows]}


@router.get("/vacancies/{vacancy_id}")
def vacancy_detail(vacancy_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    v = db.get(Vacancy, vacancy_id)
    if v is None:
        raise HTTPException(404, "vacancy not found")
    analysis = db.query(AIAnalysis).filter(AIAnalysis.vacancy_id == v.id).first()
    application = db.query(Application).filter(Application.vacancy_id == v.id).first()
    contact = db.query(Contact).filter(Contact.vacancy_id == v.id).first()
    wa = db.query(WhatsAppMessage).filter(WhatsAppMessage.vacancy_id == v.id).first()
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.vacancy_id == v.id)
        .order_by(AuditLog.created_at)
        .all()
    )
    return {
        "vacancy": {
            **_vacancy_row(v),
            "area": v.area,
            "salary_from": v.salary_from,
            "salary_to": v.salary_to,
            "salary_currency": v.salary_currency,
            "schedule": v.schedule,
            "experience": v.experience,
            "employment": v.employment,
            "description": v.description,
            "attention_reason": v.attention_reason,
            "external_id": v.external_id,
        },
        "analysis": {
            "score": analysis.score,
            "experience_match": analysis.experience_match,
            "skills_match": analysis.skills_match,
            "title_match": analysis.title_match,
            "salary_match": analysis.salary_match,
            "format_match": analysis.format_match,
            "reasons": json.loads(analysis.reasons or "[]"),
            "risks": json.loads(analysis.risks or "[]"),
            "provider": analysis.provider,
        }
        if analysis
        else None,
        "application": {
            "status": application.status,
            "cover_letter": application.cover_letter,
            "operation_id": application.provider_operation_id,
            "error": application.error,
            "created_at": application.created_at.isoformat(),
        }
        if application
        else None,
        "contact": {
            "name": contact.name,
            "phone": contact.phone,
            "email": contact.email,
        }
        if contact
        else None,
        "whatsapp": {"status": wa.status, "body": wa.body, "phone": wa.phone}
        if wa
        else None,
        "logs": [
            {"at": l.created_at.isoformat(), "action": l.action, "detail": l.detail}
            for l in logs
        ],
    }


@router.get("/attention")
def attention(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = (
        db.query(Vacancy)
        .filter(Vacancy.status == VacancyStatus.NEEDS_ATTENTION.value)
        .order_by(Vacancy.discovered_at.desc())
        .limit(200)
        .all()
    )
    return {
        "count": len(rows),
        "items": [
            {**_vacancy_row(v), "reason": v.attention_reason} for v in rows
        ],
    }


@router.get("/runs")
def runs(limit: int = 30, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = (
        db.query(SystemRun).order_by(SystemRun.started_at.desc()).limit(limit).all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "found": r.found,
                "new": r.new,
                "duplicates": r.duplicates,
                "matched": r.matched,
                "review": r.review,
                "rejected": r.rejected,
                "applied": r.applied,
                "errors": r.errors,
                "ok": r.ok,
                "detail": r.detail,
            }
            for r in rows
        ]
    }


# ── Settings ───────────────────────────────────────────────────────────────
@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)) -> dict[str, Any]:
    return AppSetting.all_as_dict(db)


@router.post("/settings")
def update_settings(
    payload: dict[str, Any] = Body(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    allowed = set(AppSetting.DEFAULTS.keys())
    updated = []
    for key, value in payload.items():
        if key not in allowed:
            continue
        AppSetting.set(db, key, value)
        updated.append(key)
    db.commit()
    # Apply live interval change to the scheduler.
    if "search_interval_hours" in updated:
        try:
            hours = float(payload["search_interval_hours"])
            MANAGER.reschedule(hours)
        except (TypeError, ValueError):
            pass
    return {"updated": updated}


# ── Control ────────────────────────────────────────────────────────────────
@router.post("/control/run-now")
def run_now() -> dict[str, str]:
    MANAGER.run_cycle_now()
    return {"status": "scheduled"}


@router.post("/control/mode")
def set_mode(
    payload: dict[str, str] = Body(...), db: Session = Depends(get_db)
) -> dict[str, str]:
    mode = payload.get("mode")
    if mode not in ("dry_run", "production"):
        raise HTTPException(400, "mode must be dry_run or production")
    AppSetting.set(db, "run_mode", mode)
    db.commit()
    return {"run_mode": mode}
