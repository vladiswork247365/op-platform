"""Component health checks and system self-diagnostics."""
from __future__ import annotations

import os
import shutil
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .ai import build_ai
from .config import Settings, get_settings
from .models import ErrorLog, RetryStatus, RetryTask, SystemRun, utcnow
from .sources import build_source

ONLINE = "ONLINE"
DEGRADED = "DEGRADED"
ERROR = "ERROR"


def _component(status: str, detail: str = "") -> dict[str, str]:
    return {"status": status, "detail": detail}


def check_database(db: Session) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return _component(ONLINE, "database reachable")
    except Exception as exc:  # noqa: BLE001
        return _component(ERROR, f"db error: {exc}")


def check_source(settings: Settings, deep: bool = False) -> dict[str, str]:
    try:
        source = build_source(settings)
        if not deep:
            return _component(ONLINE, f"source={source.name}")
        ok, detail = source.healthcheck()
        return _component(ONLINE if ok else ERROR, detail)
    except Exception as exc:  # noqa: BLE001
        return _component(ERROR, str(exc))


def check_ai(settings: Settings, deep: bool = False) -> dict[str, str]:
    try:
        ai = build_ai(settings)
        if not deep or ai.name == "mock":
            return _component(ONLINE, f"provider={ai.name}")
        ok, detail = ai.healthcheck()
        return _component(ONLINE if ok else ERROR, detail)
    except Exception as exc:  # noqa: BLE001
        return _component(ERROR, str(exc))


def scheduler_status(scheduler) -> dict[str, str]:
    if scheduler is None:
        return _component(DEGRADED, "scheduler not started")
    try:
        running = getattr(scheduler, "running", False)
        jobs = len(scheduler.get_jobs()) if running else 0
        return _component(ONLINE if running else ERROR, f"jobs={jobs}")
    except Exception as exc:  # noqa: BLE001
        return _component(ERROR, str(exc))


def last_successful_cycle(db: Session) -> str | None:
    row = (
        db.query(SystemRun)
        .filter(SystemRun.ok.is_(True), SystemRun.finished_at.isnot(None))
        .order_by(SystemRun.finished_at.desc())
        .first()
    )
    return row.finished_at.isoformat() if row and row.finished_at else None


def queue_depth(db: Session) -> int:
    return (
        db.query(RetryTask)
        .filter(RetryTask.status == RetryStatus.PENDING.value)
        .count()
    )


def errors_last_24h(db: Session) -> int:
    since = utcnow() - timedelta(hours=24)
    return db.query(ErrorLog).filter(ErrorLog.created_at >= since).count()


def build_health(db: Session, scheduler=None, deep: bool = False) -> dict[str, Any]:
    settings = get_settings()
    db_c = check_database(db)
    components = {
        "api": _component(ONLINE, "up"),
        "database": db_c,
        "scheduler": scheduler_status(scheduler),
        "worker": scheduler_status(scheduler),
        "ai": check_ai(settings, deep=deep),
        "vacancy_source": check_source(settings, deep=deep),
        "whatsapp": _component(DEGRADED, "not configured"),
    }
    q = queue_depth(db) if db_c["status"] == ONLINE else -1
    errs = errors_last_24h(db) if db_c["status"] == ONLINE else -1
    last_ok = last_successful_cycle(db) if db_c["status"] == ONLINE else None

    statuses = [c["status"] for k, c in components.items() if k != "whatsapp"]
    if ERROR in statuses:
        overall = ERROR
    elif DEGRADED in statuses:
        overall = DEGRADED
    else:
        overall = ONLINE

    return {
        "status": overall,
        "components": components,
        "last_successful_cycle": last_ok,
        "queue_depth": q,
        "errors_24h": errs,
        "run_mode": settings.run_mode,
    }


def self_diagnostic(db: Session, scheduler=None) -> dict[str, Any]:
    """Extended daily system check. Returns a report dict (also usable by E2E)."""
    report = build_health(db, scheduler=scheduler, deep=True)

    # Disk / memory (best-effort, never fatal).
    disk = shutil.disk_usage(os.getcwd())
    report["disk_free_mb"] = round(disk.free / 1024 / 1024)
    try:
        with open("/proc/meminfo") as fh:
            mem = {
                line.split(":")[0]: line.split(":")[1].strip()
                for line in fh
                if ":" in line
            }
        report["mem_available"] = mem.get("MemAvailable", "n/a")
    except OSError:
        report["mem_available"] = "n/a"

    # Stuck retry tasks (pending and long overdue).
    stuck = (
        db.query(RetryTask)
        .filter(
            RetryTask.status == RetryStatus.PENDING.value,
            RetryTask.next_attempt_at < utcnow() - timedelta(hours=6),
        )
        .count()
    )
    report["stuck_tasks"] = stuck
    report["healthy"] = report["status"] != ERROR and stuck == 0
    return report
