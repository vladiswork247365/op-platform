"""POST /webhook/tool — async callback от видео-инструмента.

По external_job_id находим job, кладём выход инструмента, будим воркер на сборку
(stage=assembling). Разбор payload — через адаптер (единственная сменная деталь).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import get_adapter
from ..config import settings
from ..db import get_db
from ..models import Job

router = APIRouter(tags=["tool"])


@router.post("/webhook/tool")
async def tool_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()

    external_id = payload.get("external_job_id") or payload.get("id") or payload.get("job_id")
    if not external_id:
        return {"ok": False, "reason": "no external_job_id"}

    job = db.execute(
        select(Job).where(Job.external_job_id == str(external_id))
    ).scalar_one_or_none()
    if not job:
        return {"ok": False, "reason": "job not found"}

    # поздний callback по уже отменённой/готовой задаче — игнорируем
    if job.status in ("canceled", "done", "error"):
        return {"ok": True, "ignored": job.status}

    snapshot = job.settings_snapshot or {}
    adapter = get_adapter(snapshot.get("tool") or settings.TOOL)
    parsed = adapter.parse_callback(payload)

    if parsed.get("status") == "failed" or not parsed.get("output_url"):
        job.status = "error"
        job.error_text = f"[rendering] инструмент вернул ошибку: {parsed.get('error') or parsed}"
        db.commit()
        return {"ok": True, "status": "error"}

    # кладём выход инструмента и переводим в assembling — воркер подхватит
    job.tool_output_url = parsed["output_url"]
    if parsed.get("cost") is not None:
        job.cost = parsed["cost"]
    job.stage = "assembling"
    db.commit()
    return {"ok": True, "status": "queued_for_assembly"}
