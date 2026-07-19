from datetime import timedelta

from app.config import get_settings
from app.models import (
    Application,
    ApplyStatus,
    AppSetting,
    RetryStatus,
    RetryTask,
    Vacancy,
    VacancyStatus,
    utcnow,
)
from app.pipeline import process_retries
from app.retry import BACKOFF, apply_idempotency_key, due_tasks, enqueue, schedule_next
from app.scheduler import CYCLE_JOB, DIAG_JOB, RETRY_JOB, SchedulerManager


def test_backoff_schedule_and_failure_cap(db):
    task = enqueue(db, "apply", "apply:1", vacancy_id=1)
    db.commit()
    settings = get_settings()

    schedule_next(db, task, "temp error", settings.max_retries)
    assert task.attempts == 1
    assert task.status == RetryStatus.PENDING.value
    assert task.next_attempt_at > utcnow()

    # Exhaust retries -> FAILED, never retried again.
    for _ in range(settings.max_retries):
        schedule_next(db, task, "temp error", settings.max_retries)
    assert task.status == RetryStatus.FAILED.value


def test_due_tasks_respects_time(db):
    t = enqueue(db, "apply", "apply:2", vacancy_id=2)
    t.next_attempt_at = utcnow() + timedelta(hours=1)
    db.commit()
    assert t not in due_tasks(db)
    t.next_attempt_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert t in due_tasks(db)


def test_process_retries_completes_on_recovery(db):
    AppSetting.set(db, "run_mode", "production")
    db.commit()
    v = Vacancy(source="mock", external_id="MOCK-1001", title="Sales Manager",
                company="Acme", status=VacancyStatus.APPLY_PENDING.value)
    db.add(v)
    db.commit()
    db.add(Application(vacancy_id=v.id, status=ApplyStatus.APPLY_FAILED.value,
                       cover_letter="Здравствуйте! Готов обсудить вакансию.",
                       idempotency_key=apply_idempotency_key(v.id)))
    enqueue(db, "apply", apply_idempotency_key(v.id), vacancy_id=v.id)
    db.commit()

    processed = process_retries(db)
    db.commit()
    assert processed == 1
    assert v.applied is True
    task = db.query(RetryTask).first()
    assert task.status == RetryStatus.DONE.value


def test_scheduler_manager_arms_and_stops():
    mgr = SchedulerManager()
    mgr.start()
    try:
        ids = {j.id for j in mgr.scheduler.get_jobs()}
        assert {CYCLE_JOB, RETRY_JOB, DIAG_JOB}.issubset(ids)
        assert mgr.scheduler.running is True
    finally:
        mgr.shutdown()
    assert mgr.scheduler.running is False
