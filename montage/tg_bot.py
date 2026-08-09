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
    from pyrogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton,
                                ReplyKeyboardMarkup, KeyboardButton)
except ImportError:
    sys.exit("❌ Не установлен Pyrogram. Выполни:  pip3 install pyrogram tgcrypto")

sys.path.insert(0, HERE)
import reel_types  # noqa: E402  — типы роликов: свои правила + папка-библиотека
import autorun     # noqa: E402  — готовая process(watch, out, fps, hook, grayscale) → (reel, verdict)
import transcribe  # noqa: E402  — распознавание голосового ТЗ (faster-whisper)
import director     # noqa: E402  — AI-режиссёр (ТЗ+речь → настройки через OpenRouter)
try:
    import qc       # noqa: E402  — авто-контроль качества («вторые мозги»)
except Exception:
    qc = None
try:
    import eleven    # noqa: E402  — озвучка/клон голоса (ElevenLabs)
    import voiceover # noqa: E402  — режим «говорю без звука»
except Exception:
    eleven = voiceover = None

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
VOICE_RE = r"(озвуч\w*|наложи\s+голос|без\s+звука|начита\w*|проговор\w*|голос(?:ом)?\s+клон\w*)"
DENSE_RE = r"(джампкат\w*|jumpcut|динамичн\w*\s+монтаж|част\w*\s+рез\w*|плотн\w*\s+монтаж|нарезк\w*\s+покруче|как\s+у\s+блогер\w*)"
GO_WORDS = {"го", "гоу", "поехали", "погнали", "генерируй", "генери", "генерь",
            "монтируй", "начинай", "старт", "готово", "давай", "собирай", "сделай"}

baskets = {}  # chat_id -> {files, job, brief, status, running}


NEW_BTN = "🎬 Создать новый ролик"
MAIN_KB = ReplyKeyboardMarkup([[KeyboardButton(NEW_BTN)]], resize_keyboard=True)


def _types_kb():
    """Инлайн-кнопки выбора типа ролика (по 1 в ряд — длинные названия)."""
    rows = [[InlineKeyboardButton(reel_types.title(k), callback_data=f"type:{k}")]
            for k in reel_types.TYPES]
    return InlineKeyboardMarkup(rows)


@app.on_message(filters.command("start"))
async def start(_, m: "Message"):
    await m.reply(
        "👋 Я собираю Reels. Жми «🎬 Создать новый ролик» и выбери ТИП — у каждого типа "
        "свои правила монтажа и своя папка-библиотека (без путаницы).\n\n"
        "Дальше: пришли исходники (видео/фото), наговори/напиши ТЗ, потом /go.\n"
        "⚡ «джампкат» — частый рез · 🧠 сам проверяю качество · "
        "🎙 «озвучь: …» — твой клон-голос.",
        reply_markup=MAIN_KB)


@app.on_message((filters.regex(f"^{re.escape(NEW_BTN)}$") | filters.command("new")))
async def new_reel(_, m: "Message"):
    if not allowed(m):
        return
    baskets.pop(m.chat.id, None)   # начинаем ролик заново
    lines = "\n".join(f"• {reel_types.title(k)} — {reel_types.hint(k)}" for k in reel_types.TYPES)
    await m.reply("Какой ТИП ролика делаем?\n\n" + lines, reply_markup=_types_kb())


@app.on_callback_query(filters.regex(r"^type:"))
async def pick_type(_, cq):
    if ALLOW:
        u = cq.from_user
        if not (u and (str(u.id) in ALLOW or (u.username or "").lower() in ALLOW)):
            await cq.answer("Доступ ограничён", show_alert=True)
            return
    key = cq.data.split(":", 1)[1]
    if not reel_types.valid(key):
        await cq.answer("Неизвестный тип")
        return
    baskets.pop(cq.message.chat.id, None)
    b = _basket(cq.message.chat.id)
    b["type"] = key
    await cq.answer(f"Тип: {reel_types.title(key)}")
    mode = "джампкат" if reel_types.dense_default(key) else "спокойный монтаж"
    try:
        await cq.message.edit_text(
            f"✅ Тип: {reel_types.title(key)}  (по умолчанию: {mode})\n"
            f"{reel_types.hint(key)}\n\n"
            "Теперь пришли исходники (видео/фото) + ТЗ, потом /go.")
    except Exception:
        await cq.message.reply(f"✅ Тип: {reel_types.title(key)}. Пришли исходники + ТЗ, потом /go.")


def _basket(chat_id):
    b = baskets.get(chat_id)
    if not b:
        b = baskets[chat_id] = {"files": [], "job": tempfile.mkdtemp(prefix="tg_job_"),
                                "brief": "", "status": None, "running": False,
                                "type": None,             # тип ролика (кнопкой), None = по умолчанию
                                "lock": asyncio.Lock()}   # против гонки при альбомах
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
    rtype = b.get("type") or reel_types.DEFAULT
    out_dir = reel_types.out_dir(rtype)          # своя папка-библиотека под тип
    gray = bool(re.search(GRAY_RE, raw, re.I))
    voiceover_on = bool(re.search(VOICE_RE, raw, re.I))
    # тип задаёт режим по умолчанию (продающий/кейс = джампкат), ТЗ/режиссёр могут включить
    dense_on = reel_types.dense_default(rtype) or bool(re.search(DENSE_RE, raw, re.I))
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
                        dense_on = dense_on or bool(cfg.get("dense"))
                        if cfg["hook"]:
                            hook = cfg["hook"]
                reel = verdict = None
                note = ""
                # режим «говорю без звука»: озвучка скрипта клон-голосом (ElevenLabs)
                if voiceover_on:
                    if voiceover and eleven and eleven.have_key() and eleven.default_voice():
                        script = re.sub(VOICE_RE, "", cleaned, flags=re.I).strip()
                        if len(script.split()) >= 3:
                            prog["stage"] = "🎙 Озвучиваю скрипт твоим голосом"
                            res = await loop.run_in_executor(
                                None, voiceover.build, job, script, out_dir, None, FPS, 0.835, gray, None)
                            if res:
                                reel = res[0]
                            else:
                                note = "\n⚠️ Озвучка не удалась — собрал обычный ролик."
                        else:
                            note = "\n⚠️ Для озвучки пришли ТЕКСТ скрипта (что проговорить)."
                    else:
                        note = ("\n⚠️ Режим озвучки требует ELEVEN_KEY и голос "
                                "(см. montage/VOICE-SETUP.md) — собрал обычный ролик.")
                if reel is None:                # обычный монтаж (или откат)
                    prog["stage"] = ("🎬 Монтирую ролик" + (" · джампкат" if dense_on else "")
                                     + (" · ч/б" if gray else ""))
                    reel, verdict = await loop.run_in_executor(
                        None, lambda: autorun.process(job, out_dir, FPS, hook, gray,
                                                      stage_file, True, dense_on))
            finally:
                stop.set()
                await anim                  # гасим анимацию перед финальными сообщениями
            await status.edit_text(f"⬆️ Готово за {int(time.time()-prog['t0'])}с "
                                   f"({human(os.path.getsize(reel))}). Отправляю…")
            qc_line = ("\n" + qc.summary(verdict)) if (verdict and qc) else ""
            reel_types.log_reel(rtype, raw, reel)   # в библиотеку типа
            await client.send_video(chat_id, reel,
                caption=f"✅ Готовый Reel · тип: {reel_types.title(rtype)}\n"
                        "Залей в Instagram/TikTok — панель подтянет статистику сама."
                        + qc_line + note, reply_markup=MAIN_KB)
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
    # сериализуем скачивание (альбом = несколько сообщений разом) — уникальный номер и папка
    async with b["lock"]:
        os.makedirs(b["job"], exist_ok=True)
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
