"""Фиксированный сценарий воркера (раздел 4 ТЗ). Сценарий зашит в код.

Труба разбита на две фазы вокруг async-инструмента:
  фаза A (start_job):  accepted → downloading → rendering(submit) → ждём callback
  фаза B (finish_job): callback → assembling(FFmpeg) → delivering(R2) → done → Telegram

Любая ошибка → status=error + error_text, стоп. retry запускает job заново с шага 1.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx
from sqlalchemy.orm import Session

from .. import telegram_api
from ..adapters import get_adapter
from ..config import settings
from ..ffmpeg_assemble import assemble_master
from ..models import Job
from ..storage import get_storage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _set(db: Session, job: Job, **fields) -> None:
    for k, v in fields.items():
        setattr(job, k, v)
    db.commit()


def _mark_error(db: Session, job: Job, where: str, exc: Exception) -> None:
    job.status = "error"
    job.error_text = f"[{where}] {type(exc).__name__}: {exc}"
    db.commit()
    print(f"[worker] job {job.id} error @ {where}: {exc}")
    try:
        telegram_api.send_message(job.chat_id, f"⚠️ Ошибка обработки: {job.error_text}")
    except Exception:  # noqa: BLE001
        pass


def _fetch_to_local(url: str) -> str:
    """Скачивает URL/ file:// в локальный файл, возвращает путь (для FFmpeg)."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return url2pathname(parsed.path)
    if parsed.scheme in ("http", "https"):
        tmp = Path(tempfile.mkdtemp(prefix="cf_tool_")) / "tool_output.mp4"
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return str(tmp)
    # локальный путь как есть
    return url


# ---------------- фаза A: приём → сабмит в инструмент ----------------
def start_job(db: Session, job: Job) -> None:
    storage = get_storage()

    # шаг 1: downloading — скачать сырьё и положить в R2
    try:
        local_src = telegram_api.download_source(job.source_ref)
        src_url = storage.put_file(local_src, f"jobs/{job.id}/source{Path(local_src).suffix or '.mp4'}")
        _set(db, job, source_stored_url=src_url)
    except Exception as e:  # noqa: BLE001
        return _mark_error(db, job, "downloading", e)

    # шаг 2: заморозить пресет (страховка — обычно уже заморожен при создании job)
    if not job.settings_snapshot:
        try:
            _set(db, job, settings_snapshot=job.preset.as_snapshot())
        except Exception as e:  # noqa: BLE001
            return _mark_error(db, job, "snapshot", e)

    # шаг 3: rendering — async submit в ОДИН инструмент, ждём POST /webhook/tool
    try:
        snapshot = job.settings_snapshot or {}
        adapter = get_adapter(snapshot.get("tool") or settings.TOOL)
        _set(db, job, stage="rendering")
        external_id = adapter.submit(job, snapshot)
        _set(db, job, external_job_id=external_id)
        print(f"[worker] job {job.id} submitted to {adapter.name}: {external_id}")
    except Exception as e:  # noqa: BLE001
        return _mark_error(db, job, "rendering", e)


# ---------------- фаза B: callback → сборка → доставка ----------------
def finish_job(db: Session, job: Job) -> None:
    storage = get_storage()
    snapshot = job.settings_snapshot or {}

    # шаг 4: assembling — забрать выход инструмента и собрать мастер FFmpeg-ом
    try:
        _set(db, job, stage="assembling")
        tool_local = _fetch_to_local(job.tool_output_url)
        master_path, preview_path = assemble_master(tool_local, snapshot)
    except Exception as e:  # noqa: BLE001
        return _mark_error(db, job, "assembling", e)

    # шаг 5: delivering — залить мастер+превью в R2
    try:
        _set(db, job, stage="delivering")
        master_url = storage.put_file(master_path, f"jobs/{job.id}/master.mp4")
        preview_url = storage.put_file(preview_path, f"jobs/{job.id}/preview.jpg")
        _set(db, job, master_url=master_url, preview_url=preview_url)
    except Exception as e:  # noqa: BLE001
        return _mark_error(db, job, "delivering", e)

    # шаг 6: done — записать итог и вернуть результат в Telegram
    job.status = "done"
    job.stage = None
    job.finished_at = _now()
    db.commit()

    _deliver(job, master_path)
    print(f"[worker] job {job.id} DONE → {job.master_url}")


def _deliver(job: Job, master_path: str) -> None:
    """Выход трубы: пробуем отправить видео, при отказе (лимит/размер) — превью+ссылка."""
    name = (job.settings_snapshot or {}).get("name", "ролик")
    caption = f"✅ Готово: {name}"
    try:
        size_mb = Path(master_path).stat().st_size / 1_048_576
    except OSError:
        size_mb = 999
    sent = False
    if size_mb <= 50:  # cloud Bot API лимит отправки
        sent = telegram_api.send_video(job.chat_id, master_path, caption)
    if not sent:
        telegram_api.send_message(
            job.chat_id,
            f"{caption}\nМастер: {job.master_url}\nПревью: {job.preview_url}",
        )
