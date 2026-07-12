"""POST /webhook/telegram — вход трубы. Бот тупой: логики ноль, вся логика тут.

Из update берём video.file_id + текст-команду + chat_id → создаём job (accepted),
быстро возвращаем 200. Никакого NLP: команда = имя пресета (ключевое слово/кнопка).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Job, Preset
from .. import telegram_api

router = APIRouter(tags=["telegram"])


def _extract(update: dict) -> tuple[int | None, str | None, str | None]:
    """→ (chat_id, source_ref, command). Тупое извлечение, без разбора смысла."""
    msg = update.get("message") or update.get("channel_post") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    # команда: текст сообщения или подпись к видео (ключевое слово, не фраза)
    command = (msg.get("text") or msg.get("caption") or "").strip()
    # сырьё: приоритет video, дальше document/animation
    source_ref = None
    for key in ("video", "animation"):
        if msg.get(key):
            source_ref = msg[key].get("file_id")
            break
    if not source_ref and msg.get("document"):
        source_ref = msg["document"].get("file_id")
    return chat_id, source_ref, command or None


def _match_preset(db: Session, command: str) -> Preset | None:
    # ключевое слово = имя пресета, регистронезависимо. Берём первое слово команды.
    keyword = command.split()[0].lstrip("/").lower() if command else ""
    if not keyword:
        return None
    return db.execute(
        select(Preset).where(func.lower(Preset.name) == keyword)
    ).scalar_one_or_none()


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    # опциональная проверка секрета из setWebhook
    if settings.TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        return {"ok": False, "reason": "bad secret"}

    update = await request.json()
    chat_id, source_ref, command = _extract(update)

    if not chat_id:
        return {"ok": True}  # нечего обрабатывать — молча 200

    if not source_ref:
        telegram_api.send_message(chat_id, "Пришлите видео с командой (имя пресета) в подписи.")
        return {"ok": True}

    preset = _match_preset(db, command or "")
    if not preset:
        names = ", ".join(n for (n,) in db.execute(select(Preset.name)).all()) or "нет пресетов"
        telegram_api.send_message(chat_id, f"Неизвестная команда. Доступные: {names}")
        return {"ok": True}

    # создаём job сразу с замороженным пресетом (snapshot на момент создания)
    job = Job(
        preset_id=preset.id,
        source_ref=source_ref,
        chat_id=chat_id,
        status="accepted",
        settings_snapshot=preset.as_snapshot(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    telegram_api.send_message(chat_id, f"Принято в работу: «{preset.name}». Задача {job.id}.")
    return {"ok": True, "job_id": str(job.id)}
