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
import re
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
import autorun     # noqa: E402  — готовая process(watch, out, fps, hook, grayscale)
import transcribe  # noqa: E402  — распознавание голосового ТЗ (faster-whisper)
import director     # noqa: E402  — AI-режиссёр (ТЗ+речь → настройки через OpenRouter)

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


GRAY_RE = r"(ч[её]рно[- ]?бел\w*|монохром\w*|grayscale|\bч/?б\b|\bbw\b|\bсер(?:ый|ым|ом|ое|еньк\w*)\b|#чб)"
GO_WORDS = {"го", "гоу", "поехали", "погнали", "генерируй", "генери", "генерь",
            "монтируй", "начинай", "старт", "готово", "давай", "собирай", "сделай"}

baskets = {}  # chat_id -> {files, job, brief, status, running}


@app.on_message(filters.command("start"))
async def start(_, m: "Message"):
    await m.reply(
        "👋 Я собираю Reels. Порядок работы:\n\n"
        "1️⃣ Пришли ИСХОДНИКИ — одно или несколько видео/фото.\n"
        "2️⃣ Наговори или напиши ТЗ — какой ролик нужен (голосовое понимаю). "
        "Скажешь «чёрно-белый» — сделаю ч/б.\n"
        "3️⃣ Досылай ещё или скажи /go (или «генерируй») — соберу ролик.\n\n"
        "Видео лучше как файл (до 2 ГБ).")


def _basket(chat_id):
    b = baskets.get(chat_id)
    if not b:
        b = baskets[chat_id] = {"files": [], "job": tempfile.mkdtemp(prefix="tg_job_"),
                                "brief": "", "status": None, "running": False}
    return b


def _is_go(text):
    t = re.sub(r"[^0-9a-zа-яё ]", "", (text or "").lower()).strip()
    words = t.split()
    return bool(words) and len(words) <= 2 and any(w in GO_WORDS for w in words)


async def _say(b, m, text):
    if b["status"] is None:
        b["status"] = await m.reply(text)
    else:
        try:
            await b["status"].edit_text(text)
        except Exception:
            b["status"] = await m.reply(text)


async def _prompt(b, m):
    bnote = f"\n📝 ТЗ: «{b['brief'][:70]}»" if b["brief"] else "\n📝 ТЗ пока нет — наговори или напиши."
    await _say(b, m, f"🧺 Исходников: {len(b['files'])}.{bnote}\n"
                     "Пришли ещё, добавь ТЗ, или /go — генерирую.")


async def _process_basket(client, chat_id):
    b = baskets.get(chat_id)
    if not b or b["running"] or not b["files"]:
        return
    b["running"] = True
    status, job, n, raw = b["status"], b["job"], len(b["files"]), (b["brief"] or "")
    gray = bool(re.search(GRAY_RE, raw, re.I))
    cleaned = re.sub(GRAY_RE, "", raw, flags=re.I).strip()
    hook = cleaned if 0 < len(cleaned.split()) <= 6 else None   # запасной вариант без режиссёра
    stage_file = os.path.join(job, "_stage.txt")
    prog = {"stage": f"🚀 Запускаю сборку ({n} файл.)…", "t0": time.time()}
    stop = asyncio.Event()

    async def animate():
        frames = "◐◓◑◒"
        i = 0
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=3)
                break                       # остановили — выходим
            except asyncio.TimeoutError:
                pass
            stage = prog["stage"]
            try:                            # движок мог записать свой этап
                s = open(stage_file, encoding="utf-8").read().strip()
                if s:
                    stage = s
            except Exception:
                pass
            el = int(time.time() - prog["t0"])
            mm, ss = divmod(el, 60)
            clock = f"{mm}:{ss:02d}" if mm else f"{ss} сек"
            try:
                await status.edit_text(f"{stage}  {frames[i % 4]}\n⏱ прошло {clock}")
            except Exception:
                pass
            i += 1

    async with render_lock:
        anim = asyncio.create_task(animate())
        try:
            try:
                loop = asyncio.get_event_loop()
                # AI-режиссёр: если есть ключ OpenRouter — по ТЗ + речи сам решает ч/б и хук
                if raw and os.environ.get("OPENROUTER_API_KEY"):
                    prog["stage"] = "🧠 AI-режиссёр читает ТЗ и речь"
                    firstvid = next((f for f in b["files"]
                                     if os.path.splitext(f)[1].lower() in VIDEO_EXT), None)
                    tr = (await loop.run_in_executor(None, transcribe.transcribe_text, firstvid)
                          if firstvid else "") or ""
                    cfg = await loop.run_in_executor(None, director.direct, raw, tr)
                    if cfg:
                        gray = cfg["grayscale"] or gray
                        if cfg["hook"]:
                            hook = cfg["hook"]
                prog["stage"] = "🎬 Монтирую ролик" + (" · ч/б" if gray else "")
                reel = await loop.run_in_executor(
                    None, autorun.process, job, OUT_DIR, FPS, hook, gray, stage_file)
            finally:
                stop.set()
                await anim                  # гасим анимацию перед финальными сообщениями
            await status.edit_text(f"⬆️ Готово за {int(time.time()-prog['t0'])}с "
                                   f"({human(os.path.getsize(reel))}). Отправляю…")
            await client.send_video(chat_id, reel,
                caption="✅ Готовый Reel. Залей в Instagram/TikTok — панель подтянет статистику сама.")
            await status.delete()
        except Exception as e:
            stop.set()
            try:
                await status.edit_text(f"❌ Ошибка монтажа: {str(e)[:200]}")
            except Exception:
                pass
        finally:
            shutil.rmtree(job, ignore_errors=True)
            baskets.pop(chat_id, None)


@app.on_message(filters.command("go"))
async def go(client, m: "Message"):
    if not allowed(m):
        return
    b = baskets.get(m.chat.id)
    if not b or not b["files"]:
        await m.reply("Сначала пришли исходники (видео/фото), потом /go.")
        return
    await _process_basket(client, m.chat.id)


@app.on_message(filters.video | filters.document | filters.animation | filters.photo)
async def on_media(client, m: "Message"):
    if not allowed(m):
        await m.reply("⛔️ Доступ ограничён. Попроси добавить тебя в TG_ALLOW.")
        return
    b = _basket(m.chat.id)
    if b["running"]:
        await m.reply("⏳ Уже монтирую — дождись ролика.")
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
    if m.caption and not b["brief"]:
        b["brief"] = m.caption.strip()
    idx = len(b["files"])
    dst = os.path.join(b["job"], f"{idx:02d}_{os.path.basename(base)}")
    await _say(b, m, f"📥 Качаю {kind} #{idx + 1} ({human(size)})…")
    try:
        await m.download(file_name=dst)
    except Exception as e:
        await _say(b, m, f"❌ Не смог скачать: {str(e)[:120]}")
        return
    b["files"].append(dst)
    await _prompt(b, m)


@app.on_message(filters.voice)
async def on_voice(client, m: "Message"):
    if not allowed(m):
        return
    b = _basket(m.chat.id)
    if b["running"]:
        return
    note = await m.reply("🎧 Слушаю ТЗ…")
    ogg = os.path.join(b["job"], "tz_voice.ogg")
    try:
        await m.download(file_name=ogg)
        loop = asyncio.get_event_loop()
        text = (await loop.run_in_executor(None, transcribe.transcribe_text, ogg) or "").strip()
    except Exception as e:
        await note.edit_text(f"❌ Не распознал голос: {str(e)[:100]}")
        return
    finally:
        try:
            os.remove(ogg)
        except Exception:
            pass
    if not text:
        await note.edit_text("Не расслышал 🙈 Повтори ТЗ голосом или напиши текстом.")
        return
    if _is_go(text) and b["files"]:
        await note.delete()
        await _process_basket(client, m.chat.id)
        return
    b["brief"] = (b["brief"] + " " + text).strip() if b["brief"] else text
    await note.delete()
    if not b["files"]:
        await m.reply(f"📝 ТЗ понял (голос): «{text}».\nТеперь пришли исходники (видео/фото) → потом /go.")
    else:
        await _prompt(b, m)


@app.on_message(filters.text & ~filters.command(["go", "start"]))
async def on_text(client, m: "Message"):
    if not allowed(m):
        return
    b = _basket(m.chat.id)
    if b["running"]:
        return
    text = (m.text or "").strip()
    if _is_go(text) and b["files"]:
        await _process_basket(client, m.chat.id)
        return
    b["brief"] = (b["brief"] + " " + text).strip() if b["brief"] else text
    if not b["files"]:
        await m.reply(f"📝 ТЗ понял: «{text}».\nПришли исходники (видео/фото) → потом /go.")
    else:
        await _prompt(b, m)


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print("🤖 Reels-бот запущен. Жду видео в Telegram… (Ctrl+C — стоп)")
    app.run()
