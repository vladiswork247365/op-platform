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
try:
    import scriptwriter  # noqa: E402  — AI-сценарист (Opus + завод)
    import factory_reel  # noqa: E402  — оркестратор: сценарий → ролик из 3 частей
except Exception:
    scriptwriter = factory_reel = None
try:
    import previral      # noqa: E402  — предиктор виральности ДО публикации
except Exception:
    previral = None
try:
    import trending      # noqa: E402  — рекомендация трендового звука для Инсты
except Exception:
    trending = None

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


NEW_BTN = "🚀 Создать новый ролик на миллион"
GET_SCRIPT_BTN = "📝 Получить сценарий для ролика"
ENOUGH_BTN = "✅ Сырья достаточно"
MAIN_KB = ReplyKeyboardMarkup([[KeyboardButton(NEW_BTN)]], resize_keyboard=True)
COLLECT_KB = ReplyKeyboardMarkup([[KeyboardButton(GET_SCRIPT_BTN)], [KeyboardButton(NEW_BTN)]],
                                 resize_keyboard=True)
ENOUGH_KB = ReplyKeyboardMarkup([[KeyboardButton(ENOUGH_BTN)], [KeyboardButton(NEW_BTN)]],
                                resize_keyboard=True)


def _types_kb():
    """Инлайн-кнопки выбора типа ролика (по 1 в ряд — длинные названия)."""
    rows = [[InlineKeyboardButton(reel_types.title(k), callback_data=f"type:{k}")]
            for k in reel_types.TYPES]
    return InlineKeyboardMarkup(rows)


def _script_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Утвердить и собрать (3 части)", callback_data="assemble")],
        [InlineKeyboardButton("➕ Добавить сырьё", callback_data="addsrc")],
        [InlineKeyboardButton("✏️ Изменить / добавить ТЗ", callback_data="recollect")]])


def _parts_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Правка ч.1", callback_data="edit:1"),
         InlineKeyboardButton("ч.2", callback_data="edit:2"),
         InlineKeyboardButton("ч.3", callback_data="edit:3")],
        [InlineKeyboardButton("🎬 Собрать финальный ролик", callback_data="final")]])


def _cq_allowed(cq) -> bool:
    if not ALLOW:
        return True
    u = cq.from_user
    return bool(u and (str(u.id) in ALLOW or (u.username or "").lower() in ALLOW))


def _music_mood(b) -> str:
    """Настроение музыки: приоритет — слово в ТЗ, иначе выбор Opus, иначе energetic."""
    raw = (b.get("brief") or "").lower()
    if re.search(r"спокойн|л[её]гк|минимал|эмбиент|фонов|расслаб", raw):
        return "calm"
    if re.search(r"эпичн|мощн|драйв|пафосн|масштабн", raw):
        return "epic"
    if re.search(r"энергичн|бодр|зажиг|динамичн|качов", raw):
        return "energetic"
    return (b.get("script") or {}).get("music_mood") or "energetic"


async def _live(m, initial: str):
    """Живой статус: спиннер + текущий этап + таймер. Меняй state['stage'] по ходу.
    Возвращает (status_msg, state, stop_event, task). В конце: stop.set(); await task."""
    status = await m.reply(initial)
    state = {"stage": initial, "t0": time.time()}
    stop = asyncio.Event()

    async def _loop():
        frames = "◐◓◑◒"
        i = 0
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=2.5)
                break
            except asyncio.TimeoutError:
                pass
            el = int(time.time() - state["t0"])
            mm, ss = divmod(el, 60)
            clock = f"{mm}:{ss:02d}" if mm else f"{ss} сек"
            try:
                await status.edit_text(f"{state['stage']}  {frames[i % 4]}\n⏱ прошло {clock}")
            except Exception:
                pass
            i += 1

    return status, state, stop, asyncio.create_task(_loop())


@app.on_message(filters.command("start"))
async def start(_, m: "Message"):
    await m.reply(
        "👋 Контент-завод на миллион. Как это работает:\n\n"
        f"1️⃣ Жми «{NEW_BTN}» → выбери ТИП.\n"
        "2️⃣ Кидай СЫРЬЁ за день (видео/фото) и ТЗ (текст/голос, сколько нужно).\n"
        f"3️⃣ Жми «{GET_SCRIPT_BTN}» — Opus напишет виральный сценарий твоим голосом.\n"
        "4️⃣ Утверждаешь → Claude САМ посмотрит каждый твой клип и разложит "
        "какой кадр на какую фразу, соберёт ролик и пришлёт 3 частями.\n"
        "5️⃣ Правишь части голосом → «Собрать финальный ролик» → публикуй.\n\n"
        "У каждого типа своя папка-библиотека (без путаницы).",
        reply_markup=MAIN_KB)


@app.on_message((filters.regex(f"^{re.escape(NEW_BTN)}$") | filters.command("new")))
async def new_reel(_, m: "Message"):
    if not allowed(m):
        return
    baskets.pop(m.chat.id, None)   # начинаем ролик заново
    lines = "\n".join(f"• {reel_types.title(k)} — {reel_types.hint(k)}" for k in reel_types.TYPES)
    await m.reply("Какой ТИП ролика делаем?\n\n" + lines, reply_markup=_types_kb())


@app.on_callback_query(filters.regex(r"^type:"))
async def pick_type(client, cq):
    if not _cq_allowed(cq):
        await cq.answer("Доступ ограничён", show_alert=True)
        return
    key = cq.data.split(":", 1)[1]
    if not reel_types.valid(key):
        await cq.answer("Неизвестный тип")
        return
    baskets.pop(cq.message.chat.id, None)
    b = _basket(cq.message.chat.id)
    b["type"] = key
    b["stage"] = "collect"
    await cq.answer(f"Тип: {reel_types.title(key)}")
    try:
        await cq.message.edit_text(f"✅ Тип: {reel_types.title(key)}\n{reel_types.hint(key)}")
    except Exception:
        pass
    await client.send_message(
        cq.message.chat.id,
        "📥 Кидай СЫРЬЁ (видео/фото за день, сколько угодно) и ТЗ (текстом или голосом, "
        "хоть 1, хоть 100 раз). Я всё складываю в этот ролик.\n\n"
        f"Как всё скинешь — жми «{GET_SCRIPT_BTN}».",
        reply_markup=COLLECT_KB)


@app.on_message(filters.regex(f"^{re.escape(GET_SCRIPT_BTN)}$"))
async def get_script_btn(client, m: "Message"):
    if not allowed(m):
        return
    await _make_script(client, m.chat.id, m)


@app.on_callback_query(filters.regex(r"^recollect$"))
async def cb_recollect(client, cq):
    if not _cq_allowed(cq):
        return
    b = _basket(cq.message.chat.id)
    b["stage"] = "collect"
    await cq.answer("Добавляй ТЗ/исходники")
    await client.send_message(cq.message.chat.id,
        f"Ок, добавляй ещё ТЗ или исходники. Потом снова «{GET_SCRIPT_BTN}».",
        reply_markup=COLLECT_KB)


@app.on_callback_query(filters.regex(r"^addsrc$"))
async def cb_addsrc(client, cq):
    if not _cq_allowed(cq):
        return
    b = _basket(cq.message.chat.id)
    b["stage"] = "add_more"
    await cq.answer("Кидай ещё сырьё")
    await client.send_message(cq.message.chat.id,
        f"➕ Кидай ещё видео/фото — не хватило под сценарий. Сейчас в ролике: "
        f"{len(b['files'])} шт.\nКак хватит — жми «{ENOUGH_BTN}».", reply_markup=ENOUGH_KB)


@app.on_message(filters.regex(f"^{re.escape(ENOUGH_BTN)}$"))
async def enough_btn(client, m: "Message"):
    if not allowed(m):
        return
    b = _basket(m.chat.id)
    if not b.get("script"):
        await m.reply("Сначала получи сценарий.", reply_markup=COLLECT_KB)
        return
    b["stage"] = "review_script"
    await m.reply(f"Принял. Сырья в ролике: {len(b['files'])} шт.", reply_markup=MAIN_KB)
    await m.reply("📝 Сценарий:\n\n" + scriptwriter.as_text(b["script"]), reply_markup=_script_kb())


async def _make_script(client, chat_id, m):
    b = baskets.get(chat_id)
    if not b or not b["files"]:
        await m.reply("Сначала кинь исходники (видео/фото), потом жми кнопку.")
        return
    if not (scriptwriter and os.environ.get("OPENROUTER_API_KEY")):
        await m.reply("Нужен OPENROUTER_API_KEY (Opus) для сценария. Впиши в montage/.env.")
        return
    status, state, stop, task = await _live(
        m, f"🧠 Беру {len(b['files'])} исходн. и {b.get('tz_count', 0)} ТЗ…")
    script = None
    try:
        loop = asyncio.get_event_loop()
        firstvid = next((f for f in b["files"]
                         if os.path.splitext(f)[1].lower() in VIDEO_EXT), None)
        tr = ""
        if firstvid:
            state["stage"] = "🎙 Распознаю речь в сырье…"
            tr = (await loop.run_in_executor(None, transcribe.transcribe_text, firstvid)) or ""
        state["stage"] = "🧠 Захожу в панель — работа над ошибками…"
        await asyncio.sleep(0.4)
        state["stage"] = "✍️ Пишу виральный сценарий с учётом прошлых роликов (Opus)…"
        rt = b.get("type") or reel_types.DEFAULT       # ключ формата → механики формата
        script = await loop.run_in_executor(None, lambda: scriptwriter.write_script(b["brief"], tr, rt))
    finally:
        stop.set()
        await task
    if not script:
        why = getattr(scriptwriter, "LAST_ERROR", "") or "нет ответа от OpenRouter"
        await status.edit_text(f"❌ Сценарий не собрался.\nПричина: {why}")
        return
    b["script"] = script
    b["stage"] = "review_script"
    await status.edit_text("📝 Сценарий готов:\n\n" + scriptwriter.as_text(script),
                           reply_markup=_script_kb())


@app.on_callback_query(filters.regex(r"^assemble$"))
async def cb_assemble(client, cq):
    if not _cq_allowed(cq):
        return
    await cq.answer("Собираю ролик…")
    await _assemble(client, cq.message.chat.id, cq.message)


async def _assemble(client, chat_id, m):
    b = baskets.get(chat_id)
    if not b or not b.get("script"):
        await m.reply("Сначала сценарий — жми «Получить сценарий».")
        return
    if not (factory_reel and eleven and eleven.have_key() and eleven.default_voice()):
        await m.reply("Для сборки нужен ElevenLabs (ELEVEN_KEY + ELEVEN_VOICE_ID) — см. VOICE-SETUP.md.")
        return
    if b.get("running"):
        return
    b["running"] = True
    status = await m.reply("🎬 Собираю ролик: озвучка + твои кадры + субтитры + плашки + музыка…")
    loop = asyncio.get_event_loop()
    gray = bool(re.search(GRAY_RE, b.get("brief") or "", re.I))
    rtype = b.get("type") or reel_types.DEFAULT
    out = reel_types.out_dir(rtype)
    vid = eleven.default_voice()

    def _sf(t):
        try:
            asyncio.run_coroutine_threadsafe(status.edit_text(t), loop)
        except Exception:
            pass
    async with render_lock:
        try:
            reel = await loop.run_in_executor(
                None, lambda: factory_reel.build(b["job"], b["script"], out, vid, gray,
                                                 _music_mood(b), FPS, _sf, rtype))
            if not reel:
                await status.edit_text("❌ Не собралось (озвучка). Проверь баланс ElevenLabs.")
                return
            b["reel"] = reel
            parts = await loop.run_in_executor(None, lambda: factory_reel.split_three(reel, b["job"]))
            b["parts"] = parts
            b["stage"] = "review_parts"
            await status.edit_text("Готовы 3 части — глянь каждую 👇")
            for i, p in enumerate(parts):
                await client.send_video(chat_id, p, caption=f"Часть {i + 1}/3")
            # предиктор виральности ДО публикации — Claude смотрит готовый ролик глазами
            if previral and os.environ.get("OPENROUTER_API_KEY"):
                pv = await client.send_message(chat_id, "🔮 Оцениваю виральность до публикации…")
                try:
                    v = await loop.run_in_executor(None, lambda: previral.check(reel, b["script"], rtype))
                    if v:
                        b["previral"] = v
                        await pv.edit_text(previral.as_text(v))
                    else:
                        await pv.delete()
                except Exception:
                    try:
                        await pv.delete()
                    except Exception:
                        pass
            await client.send_message(
                chat_id, "Правки по частям — жми кнопку и наговори/напиши голосом. "
                "Всё устраивает — «Собрать финальный ролик».", reply_markup=_parts_kb())
        except Exception as e:
            await status.edit_text(f"❌ Ошибка сборки: {str(e)[:200]}")
        finally:
            b["running"] = False


@app.on_callback_query(filters.regex(r"^edit:"))
async def cb_edit(client, cq):
    if not _cq_allowed(cq):
        return
    n = cq.data.split(":", 1)[1]
    b = _basket(cq.message.chat.id)
    b["await_edit"] = n
    await cq.answer(f"Правка к части {n}")
    await client.send_message(cq.message.chat.id,
        f"✏️ Наговори или напиши правку к ЧАСТИ {n} (что поменять).")


@app.on_callback_query(filters.regex(r"^final$"))
async def cb_final(client, cq):
    if not _cq_allowed(cq):
        return
    await cq.answer("Готовлю финал…")
    await _finalize(client, cq.message.chat.id, cq.message)


async def _finalize(client, chat_id, m):
    b = baskets.get(chat_id)
    if not b or not b.get("reel"):
        await m.reply("Нечего финалить — сначала собери ролик.")
        return
    if b.get("running"):
        return
    reel = b["reel"]
    # если были правки — перепишем сценарий с их учётом и пересоберём
    if b.get("edits") and scriptwriter and factory_reel:
        b["running"] = True
        status = await m.reply("🎬 Вношу правки и пересобираю финал…")
        loop = asyncio.get_event_loop()
        edits_txt = "; ".join(f"часть {n}: {t}" for n, t in b["edits"])
        new_brief = (b.get("brief") or "") + "\nПРАВКИ АВТОРА: " + edits_txt
        rt = b.get("type") or reel_types.DEFAULT       # ключ формата → механики формата
        gray = bool(re.search(GRAY_RE, b.get("brief") or "", re.I))
        out = reel_types.out_dir(rt)
        vid = eleven.default_voice() if eleven else None
        async with render_lock:
            try:
                sc = await loop.run_in_executor(None, lambda: scriptwriter.write_script(new_brief, "", rt))
                if sc:
                    b["script"] = sc
                r = await loop.run_in_executor(
                    None, lambda: factory_reel.build(b["job"], b["script"], out, vid, gray,
                                                     _music_mood(b), FPS, lambda t: None, rt))
                if r:
                    reel = b["reel"] = r
            except Exception as e:
                await status.edit_text(f"❌ Ошибка пересборки: {str(e)[:150]}")
            finally:
                b["running"] = False
        try:
            await status.delete()
        except Exception:
            pass
    rt = b.get("type") or reel_types.DEFAULT
    reel_types.log_reel(rt, b.get("brief") or "", reel)
    await client.send_video(chat_id, reel,
        caption="✅ ФИНАЛЬНЫЙ РОЛИК — голос + субтитры, БЕЗ вшитой музыки (специально под "
                "трендовый звук).\nЗалей в Instagram — панель подтянет статистику, через 6ч будет разбор.",
        reply_markup=MAIN_KB)
    # какой трендовый звук добавить ВРУЧНУЮ в Инсте (моторика алгоритма)
    sound = (b.get("previral") or {}).get("sound")
    pace = (b.get("script") or {}).get("pace", "medium")
    msg = trending.recommend(_music_mood(b), rt, pace) if trending else ""
    if sound:
        msg = f"🎵 ЗВУК ДЛЯ ИНСТЫ — добавь ВРУЧНУЮ.\n• Под этот ролик: {sound}\n\n" + msg
    if msg:
        await client.send_message(chat_id, msg)
    baskets.pop(chat_id, None)


def _basket(chat_id):
    b = baskets.get(chat_id)
    if not b:
        b = baskets[chat_id] = {"files": [], "job": tempfile.mkdtemp(prefix="tg_job_"),
                                "brief": "", "status": None, "running": False,
                                "type": None,             # тип ролика (кнопкой), None = по умолчанию
                                "stage": None,            # collect / review_script / review_parts
                                "await_edit": None,       # ждём правку к части N (голосом/текстом)
                                "tz_count": 0,            # сколько ТЗ принято
                                "edits": [], "script": None, "reel": None, "parts": [],
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
    if b.get("stage") == "add_more":     # догрузка сырья после сценария
        await m.reply(f"➕ В ролике сырья: {len(b['files'])} шт. Кидай ещё или жми «{ENOUGH_BTN}».",
                      reply_markup=ENOUGH_KB)
        return
    cnt = b.get("tz_count", 0)
    bnote = f"\n📝 ТЗ принято: {cnt} шт." if cnt else "\n📝 ТЗ пока нет — наговори или напиши."
    tail = (f"\nКак всё скинешь — жми «{GET_SCRIPT_BTN}»." if b.get("type")
            else "\nПришли ещё, добавь ТЗ, или /go — генерирую.")
    await _say(b, m, f"🧺 Исходников: {len(b['files'])}.{bnote}{tail}")


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
        b["tz_count"] = b.get("tz_count", 0) + 1
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
        await note.edit_text("Не расслышал 🙈 Повтори голосом или напиши текстом.")
        return
    if b.get("await_edit"):                       # правка к части (голосом)
        n = b["await_edit"]
        b["edits"].append((n, text))
        b["await_edit"] = None
        await note.delete()
        await m.reply(f"✏️ Правка к части {n} принята: «{text[:80]}».\n"
                      "Ещё правки — жми кнопку части, или собери финал:", reply_markup=_parts_kb())
        return
    if _is_go(text) and b["files"]:
        await note.delete()
        await _process_basket(client, m.chat.id)
        return
    b["brief"] = (b["brief"] + " " + text).strip() if b["brief"] else text
    b["tz_count"] = b.get("tz_count", 0) + 1
    await note.delete()
    if not b["files"]:
        await m.reply(f"📝 ТЗ #{b['tz_count']} принято (голос): «{text[:60]}».\n"
                      "Пришли исходники (видео/фото).")
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
    if b.get("await_edit"):                       # правка к части (текстом)
        n = b["await_edit"]
        b["edits"].append((n, text))
        b["await_edit"] = None
        await m.reply(f"✏️ Правка к части {n} принята: «{text[:80]}».\n"
                      "Ещё правки — жми кнопку части, или собери финал:", reply_markup=_parts_kb())
        return
    if _is_go(text) and b["files"]:
        await _process_basket(client, m.chat.id)
        return
    b["brief"] = (b["brief"] + " " + text).strip() if b["brief"] else text
    b["tz_count"] = b.get("tz_count", 0) + 1
    if not b["files"]:
        await m.reply(f"📝 ТЗ #{b['tz_count']} принято: «{text[:60]}».\n"
                      "Пришли исходники (видео/фото).")
    else:
        await m.reply(f"📝 ТЗ #{b['tz_count']} принято.")
        await _prompt(b, m)


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print("🤖 Reels-бот запущен. Жду видео в Telegram… (Ctrl+C — стоп)")
    app.run()
