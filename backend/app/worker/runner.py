"""Фоновый воркер: тянет job'ы из БД и гонит по фиксированному сценарию.

Отдельный процесс (не HTTP-ручка):  python -m app.worker.runner
Один воркер обрабатывает по одному шагу за тик. Claim через FOR UPDATE SKIP LOCKED —
безопасно и при нескольких воркерах.
"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Job
from . import pipeline

POLL_SECONDS = 1.0


def _claim_accepted(db: Session) -> Job | None:
    """Свежий job: accepted → processing/downloading (claim атомарно)."""
    job = db.execute(
        select(Job).where(Job.status == "accepted").with_for_update(skip_locked=True).limit(1)
    ).scalar_one_or_none()
    if job:
        job.status = "processing"
        job.stage = "downloading"
        db.commit()
    return job


def _claim_ready_to_finish(db: Session) -> Job | None:
    """Пришёл callback инструмента (stage=assembling, есть tool_output_url)."""
    return db.execute(
        select(Job)
        .where(
            Job.status == "processing",
            Job.stage == "assembling",
            Job.tool_output_url.isnot(None),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()


def tick() -> bool:
    """Один проход. Возвращает True, если что-то обработали."""
    with SessionLocal() as db:
        job = _claim_accepted(db)
        if job:
            pipeline.start_job(db, job)
            return True

    with SessionLocal() as db:
        job = _claim_ready_to_finish(db)
        if job:
            pipeline.finish_job(db, job)
            return True

    return False


def run() -> None:
    print("[worker] started — poll every", POLL_SECONDS, "s")
    while True:
        try:
            worked = tick()
        except Exception as e:  # noqa: BLE001 — воркер не должен падать целиком
            print(f"[worker] tick error: {e}")
            worked = False
        if not worked:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
