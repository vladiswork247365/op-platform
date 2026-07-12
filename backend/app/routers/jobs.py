"""Лента и карточка задач + retry/cancel (раздел 3 ТЗ)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Job
from ..schemas import JobList, JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobList)
def list_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(Job)
    cq = select(func.count()).select_from(Job)
    if status:
        q = q.where(Job.status == status)
        cq = cq.where(Job.status == status)
    total = db.execute(cq).scalar_one()
    items = db.execute(q.order_by(Job.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return JobList(total=total, items=items)


def _get(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get(db, job_id)


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _get(db, job_id)
    if job.status not in ("error", "canceled"):
        raise HTTPException(409, f"нельзя перезапустить из статуса {job.status}")
    # заново с шага 1: чистим всё, кроме замороженного пресета
    job.status = "accepted"
    job.stage = None
    job.error_text = None
    job.external_job_id = None
    job.source_stored_url = None
    job.tool_output_url = None
    job.master_url = None
    job.preview_url = None
    job.cost = None
    job.finished_at = None
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = _get(db, job_id)
    if job.status in ("done", "error", "canceled"):
        raise HTTPException(409, f"нельзя отменить из статуса {job.status}")
    job.status = "canceled"
    job.stage = None
    db.commit()
    db.refresh(job)
    return job
