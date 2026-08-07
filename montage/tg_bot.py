#!/usr/bin/env python3
"""Телеграм-бот приёма роликов (до 2 ГБ) → очередь → монтаж → готовый reel обратно.

Работает на MTProto (Pyrogram): тянет и отдаёт большие файлы до 2 ГБ.
Обычный Bot API качает только до 20 МБ — поэтому именно Pyrogram.

Запускать ТАМ, ГДЕ ЕСТЬ ffmpeg и конвейер (Mac/сервер), а не в облаке.

.env (montage/.env, chmod 600) — как получить см. montage/TG-SETUP.md:
  TG_API_ID     — my.telegram.org → API development tools
  TG_API_HASH   — оттуда же
  TG_BOT_TOKEN  — @BotFather
  TG_ALLOW      — (опц.) через запятую: @username или id, кому можно слать. Пусто = всем.

Запуск:  python3 montage/tg_bot.py
"""
from __future__ import annotations
import asyncio
import os
import sys
import time
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "out")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".hevc"}


def load_env():
    for path in (os.path.join(HERE, ".env"), os.path.join(ROOT, ".env")):
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def need(var):
    v = os.environ.get(var)
    if not v:
        sys.exit(f"❌ Нет {var}. Впиши в montage/.env — как получить: montage/TG-SETUP.md")
    return v


load_env()
try:
    from pyrogram import Client, filters
    from pyrogram.types import Message
except ImportError:
    sys.exit("❌ Не установлен Pyrogram. Выполни:  pip3 install pyrogram tgcrypto")

sys.path.insert(0, HERE)
import autorun  # noqa: E402  — берём готовую process(watch, out, fps)

API_ID = int(need("TG_API_ID"))
API_HASH = need("TG_API_HASH")
BOT_TOKEN = need("TG_BOT_TOKEN")
ALLOW = {x.strip().lstrip("@").lower() for x in os.environ.get("TG_ALLOW", "").split(",") if x.strip()}
FPS = int(os.environ.get("TG_FPS", "30"))

app = Client("reels_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN,
             workdir=HERE)

render_lock = asyncio.Lock()   # рендер по одному за раз
pending = 0                    # сколько в очереди на рендер


def allowed(msg: "Message") -> bool:
    if not ALLOW:
        return True
    u = msg.from_user
    return bool(u and (str(u.id) in ALLOW or (u.username or "").lower() in ALLOW))


def human(n):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


@app.on_message(filters.command("start"))
async def start(_, m: "Message"):
    await m.reply(
        "👋 Пришли мне видео (можно как файл, до 2 ГБ) — соберу вертикальный Reel: "
        "поджму паузы, нарежу динамично, добавлю субтитры и отдам готовый ролик обратно.\n\n"
        "Просто перекинь сюда видео с телефона или файлом.")


@app.on_message(filters.video | filters.document | filters.animation)
async def on_video(_, m: "Message"):
    global pending
    if not allowed(m):
        await m.reply("⛔️ Доступ ограничён. Попроси добавить тебя в TG_ALLOW.")
        return

    media = m.video or m.document or m.animation
    name = getattr(media, "file_name", None) or f"clip_{int(time.time())}.mp4"
    ext = os.path.splitext(name)[1].lower()
    if m.document and ext and ext not in VIDEO_EXT:
        await m.reply(f"Это не видео ({ext}). Пришли видеофайл.")
        return
    size = getattr(media, "file_size", 0) or 0

    status = await m.reply(f"📥 Принял «{name}» ({human(size)}). Скачиваю…")
    job = tempfile.mkdtemp(prefix="tg_job_")
    dst = os.path.join(job, os.path.basename(name) or "clip.mp4")

    # прогресс скачивания — обновляем не чаще раза в 2с
    st = {"t": 0.0}
    async def prog(cur, tot):
        now = time.time()
        if now - st["t"] >= 2 and tot:
            st["t"] = now
            try:
                await status.edit_text(f"📥 Скачиваю «{name}»… {cur*100//tot}% ({human(cur)}/{human(tot)})")
            except Exception:
                pass
    try:
        await m.download(file_name=dst, progress=prog)
    except Exception as e:
        await status.edit_text(f"❌ Не смог скачать: {str(e)[:120]}")
        return

    pending += 1
    pos = pending
    if render_lock.locked():
        await status.edit_text(f"🎬 В очереди на монтаж (перед тобой: {pos-1}). Начну, как освободится.")
    async with render_lock:
        try:
            await status.edit_text("⚙️ Монтирую: поджимаю паузы → нарезка → субтитры → рендер…")
            loop = asyncio.get_event_loop()
            reel = await loop.run_in_executor(None, autorun.process, job, OUT_DIR, FPS)
            rsize = os.path.getsize(reel)
            await status.edit_text(f"⬆️ Готово ({human(rsize)}). Отправляю ролик…")
            await m.reply_video(reel, caption="✅ Готовый Reel. Дальше — залей в Instagram/TikTok, "
                                              "и панель подтянет статистику автоматически.")
            await status.delete()
        except Exception as e:
            await status.edit_text(f"❌ Ошибка монтажа: {str(e)[:200]}")
        finally:
            pending -= 1
            import shutil
            shutil.rmtree(job, ignore_errors=True)


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print("🤖 Reels-бот запущен. Жду видео в Telegram… (Ctrl+C — стоп)")
    app.run()
