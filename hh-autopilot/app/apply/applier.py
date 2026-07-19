"""Idempotent application sending, shared by the pipeline and the retry worker.

Guarantees:
  * A vacancy that is already APPLIED is never applied again (idempotency key).
  * DRY_RUN never contacts the source — it records what WOULD be sent.
  * Temporary failures are queued for backoff retry; permanent ones are parked
    in the NEEDS_ATTENTION queue and never auto-retried.
"""
from __future__ import annotations

from ..audit import audit, log_error
from ..config import Settings
from ..cover_letter import final_check
from ..models import (
    Application,
    ApplyStatus,
    RetryStatus,
    Vacancy,
    VacancyStatus,
    utcnow,
)
from ..retry import apply_idempotency_key, enqueue, schedule_next
from ..sources.base import VacancySource
from sqlalchemy.orm import Session


def perform_apply(
    db: Session,
    settings: Settings,
    source: VacancySource,
    vacancy: Vacancy,
    cover_letter: str,
    is_production: bool,
    retry_task=None,
) -> str:
    """Apply to a vacancy. Returns an ApplyStatus value. Idempotent."""
    key = apply_idempotency_key(vacancy.id)
    app = (
        db.query(Application).filter(Application.idempotency_key == key).first()
    )

    # Idempotency: already applied -> never resend.
    if app and app.status == ApplyStatus.APPLIED.value:
        if retry_task is not None:
            retry_task.status = RetryStatus.DONE.value
        return ApplyStatus.APPLIED.value

    # Validate the letter right before sending.
    ok, reason = final_check(cover_letter, _rv_stub(vacancy))
    if not ok:
        vacancy.status = VacancyStatus.NEEDS_ATTENTION.value
        vacancy.attention_reason = f"cover letter: {reason}"
        log_error(db, "apply", f"cover letter rejected: {reason}", permanent=True)
        return ApplyStatus.SKIPPED.value

    if app is None:
        app = Application(
            vacancy_id=vacancy.id,
            status=ApplyStatus.SKIPPED.value,
            cover_letter=cover_letter,
            idempotency_key=key,
        )
        db.add(app)
        db.flush()
    else:
        app.cover_letter = cover_letter

    # DRY_RUN: record intent, send nothing.
    if not is_production:
        app.status = ApplyStatus.DRY_RUN.value
        audit(db, "apply.dry_run", vacancy.title, vacancy.id)
        return ApplyStatus.DRY_RUN.value

    # PRODUCTION: send through the official channel.
    result = source.apply(vacancy.external_id, cover_letter)
    if result.ok:
        app.status = ApplyStatus.APPLIED.value
        app.provider_operation_id = result.operation_id
        app.provider_response = result.response[:2000]
        app.error = None
        vacancy.applied = True
        vacancy.applied_at = utcnow()
        vacancy.status = VacancyStatus.APPLIED.value
        if retry_task is not None:
            retry_task.status = RetryStatus.DONE.value
        audit(db, "apply.sent", f"{vacancy.title} op={result.operation_id}", vacancy.id)
        return ApplyStatus.APPLIED.value

    # Failure.
    app.status = ApplyStatus.APPLY_FAILED.value
    app.error = result.error
    log_error(db, "apply", result.error, permanent=result.permanent)

    if result.permanent:
        vacancy.status = VacancyStatus.NEEDS_ATTENTION.value
        vacancy.attention_reason = f"apply failed (permanent): {result.error[:200]}"
        if retry_task is not None:
            retry_task.status = RetryStatus.FAILED.value
        return ApplyStatus.APPLY_FAILED.value

    # Temporary -> schedule/continue retry.
    vacancy.status = VacancyStatus.APPLY_PENDING.value
    if retry_task is None:
        enqueue(db, "apply", key, vacancy_id=vacancy.id)
    else:
        schedule_next(db, retry_task, result.error, settings.max_retries)
    return ApplyStatus.APPLY_FAILED.value


def _rv_stub(vacancy: Vacancy):
    from ..sources.base import RawVacancy

    return RawVacancy(
        external_id=vacancy.external_id,
        title=vacancy.title,
        company=vacancy.company,
    )
