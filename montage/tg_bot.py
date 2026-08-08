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
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "out")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".hevc"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
DEBOUNCE = 5  # сек ожидания новых файлов перед авто-стартом монтажа


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


baskets = {}  # chat_id -> {files, job, hook, gen, status, running} — сборка нескольких файлов


@app.on_message(filters.command("start"))
async def start(_, m: "Message"):
    await m.reply(
        "👋 Пришли ОДНО или НЕСКОЛЬКО видео/фото — соберу из них один вертикальный Reel: "
        "поджму паузы, нарежу динамично, субтитры (мимо лица), и отдам готовый ролик.\n\n"
        f"🧺 Файлы коплю в сборку и склеиваю по порядку. После последнего жду ~{DEBOUNCE}с и "
        "монтирую, или напиши /go — сразу.\n\n"
        "📝 ТЗ — добавь ПОДПИСЬ к любому файлу: текст ляжет крупным хуком в начало.\n\n"
        "Видео лучше слать как файл (до 2 ГБ).")


def _basket(chat_id):
    b = baskets.get(chat_id)
    if not b:
        b = baskets[chat_id] = {"files": [], "job": tempfile.mkdtemp(prefix="tg_job_"),
                                "hook": "", "gen": 0, "status": None, "running": False}
    return b


async def _process_basket(client, chat_id):
    b = baskets.get(chat_id)
    if not b or b["running"] or not b["files"]:
        return
    b["running"] = True
    status, job, hook, n = b["status"], b["job"], (b["hook"] or None), len(b["files"])
    async with render_lock:
        try:
            await status.edit_text(f"⚙️ Монтирую {n} файл(ов) в один ролик: паузы → нарезка → субтитры → рендер…")
            loop = asyncio.get_event_loop()
            reel = await loop.run_in_executor(None, autorun.process, job, OUT_DIR, FPS, hook)
            await status.edit_text(f"⬆️ Готово ({human(os.path.getsize(reel))}). Отправляю…")
            await client.send_video(chat_id, reel,
                caption="✅ Готовый Reel. Залей в Instagram/TikTok — панель подтянет статистику сама.")
            await status.delete()
        except Exception as e:
            await status.edit_text(f"❌ Ошибка монтажа: {str(e)[:200]}")
        finally:
            shutil.rmtree(job, ignore_errors=True)
            baskets.pop(chat_id, None)


async def _debounce(client, chat_id, gen):
    await asyncio.sleep(DEBOUNCE)
    b = baskets.get(chat_id)
    if b and b["gen"] == gen and not b["running"]:
        await _process_basket(client, chat_id)


@app.on_message(filters.command("go"))
async def go(client, m: "Message"):
    if not allowed(m):
        return
    b = baskets.get(m.chat.id)
    if not b or not b["files"]:
        await m.reply("Сборка пуста — пришли видео/фото, потом /go.")
        return
    await _process_basket(client, m.chat.id)


@app.on_message(filters.video | filters.document | filters.animation | filters.photo)
async def on_media(client, m: "Message"):
    if not allowed(m):
        await m.reply("⛔️ Доступ ограничён. Попроси добавить тебя в TG_ALLOW.")
        return
    b = _basket(m.chat.id)
    if b["running"]:
        await m.reply("⏳ Уже монтирую предыдущую сборку — дождись ролика и пришли заново.")
        return

    if m.photo:
        kind, base, size = "фото", "photo.jpg", getattr(m.photo, "file_size", 0) or 0
    else:
        media = m.video or m.document or m.animation
        base = getattr(media, "file_name", None) or "clip.mp4"
        ext = os.path.splitext(base)[1].lower()
        if m.document and ext and ext not in VIDEO_EXT and ext not in IMAGE_EXT:
            await m.reply(f"Пропускаю: {ext} — нужно видео или фото.")
            return
        kind, size = "видео", getattr(media, "file_size", 0) or 0

    if m.caption and not b["hook"]:
        b["hook"] = m.caption.strip()

    idx = len(b["files"])
    dst = os.path.join(b["job"], f"{idx:02d}_{os.path.basename(base)}")
    text = f"📥 Качаю {kind} #{idx + 1} ({human(size)})…"
    if b["status"] is None:
        b["status"] = await m.reply(text)
    else:
        try:
            await b["status"].edit_text(text)
        except Exception:
            pass
    try:
        await m.download(file_name=dst)
    except Exception as e:
        await b["status"].edit_text(f"❌ Не смог скачать файл: {str(e)[:120]}")
        return
    b["files"].append(dst)
    b["gen"] += 1
    hooknote = f" · ТЗ: «{b['hook'][:32]}»" if b["hook"] else ""
    try:
        await b["status"].edit_text(
            f"🧺 В сборке: {len(b['files'])} файл(ов){hooknote}.\n"
            f"Пришли ещё или /go — смонтирую в один ролик (авто-старт через {DEBOUNCE}с).")
    except Exception:
        pass
    asyncio.create_task(_debounce(client, m.chat.id, b["gen"]))


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print("🤖 Reels-бот запущен. Жду видео в Telegram… (Ctrl+C — стоп)")
    app.run()
