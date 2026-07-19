"""Retry scheduling with exponential backoff and idempotency.

Backoff schedule (attempt -> delay): 1 immediate, 2 +5m, 3 +15m, 4 +1h.
Idempotency keys guarantee a successful operation is never repeated even if a
worker restarts or a retry fires late.
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy.orm import Session

from .models import RetryStatus, RetryTask, utcnow

# Delay before attempt N (index 0 == first retry after the initial failure).
BACKOFF = [
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=3),
]


def apply_idempotency_key(vacancy_id: int) -> str:
    return f"apply:{vacancy_id}"


def enqueue(
    db: Session,
    kind: str,
    idempotency_key: str,
    vacancy_id: int | None = None,
    payload: dict | None = None,
) -> RetryTask | None:
    """Create a retry task unless an identical pending one already exists."""
    existing = (
        db.query(RetryTask)
        .filter(
            RetryTask.idempotency_key == idempotency_key,
            RetryTask.status == RetryStatus.PENDING.value,
        )
        .first()
    )
    if existing is not None:
        return existing
    task = RetryTask(
        kind=kind,
        vacancy_id=vacancy_id,
        idempotency_key=idempotency_key,
        payload=json.dumps(payload or {}),
        attempts=0,
        next_attempt_at=utcnow(),
        status=RetryStatus.PENDING.value,
    )
    db.add(task)
    db.flush()
    return task


def schedule_next(db: Session, task: RetryTask, error: str, max_retries: int) -> None:
    task.attempts += 1
    task.last_error = (error or "")[:2000]
    if task.attempts >= max_retries:
        task.status = RetryStatus.FAILED.value
    else:
        delay = BACKOFF[min(task.attempts - 1, len(BACKOFF) - 1)]
        task.next_attempt_at = utcnow() + delay
    db.flush()


def mark_done(db: Session, task: RetryTask) -> None:
    task.status = RetryStatus.DONE.value
    db.flush()


def due_tasks(db: Session, limit: int = 20) -> list[RetryTask]:
    return (
        db.query(RetryTask)
        .filter(
            RetryTask.status == RetryStatus.PENDING.value,
            RetryTask.next_attempt_at <= utcnow(),
        )
        .order_by(RetryTask.next_attempt_at)
        .limit(limit)
        .all()
    )
