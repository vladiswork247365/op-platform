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
import json
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
    import shots         # noqa: E402  — «глаза»: Claude смотрит сырьё (кэш _shots.json)
except Exception:
    shots = None
try:
    import weblink       # noqa: E402  — ссылка-референс к ТЗ (тянет контент по URL)
except Exception:
    weblink = None
try:
    import trendsee      # noqa: E402  — тренды «что заходит у других» (TrendSee API)
except Exception:
    trendsee = None
try:
    import trendsee_harvest  # noqa: E402  — банк трендов по 500+ ключам (кнопка /trends)
except Exception:
    trendsee_harvest = None
try:
    import trending      # noqa: E402  — рекомендация трендового звука для Инсты
except Exception:
    trending = None

API_ID = int(need("TG_API_ID"))
API_HASH = need("TG_API_HASH")
BOT_TOKEN = need("TG_BOT_TOKEN")
ALLOW = {x.strip().lstrip("@").lower() for x in os.environ.get("TG_ALLOW", "").split(",") if x.strip()}
FPS = int(os.environ.get("TG_FPS", "30"))
POLISH_TARGET = int(os.environ.get("POLISH_TARGET", "8"))   # цель по виральности (из 10)
POLISH_MAX = int(os.environ.get("POLISH_MAX", "2"))          # сколько раз авто-усиливать

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
LOOK_BTN = "👁 Claude, посмотри сырьё"
GET_SCRIPT_BTN = "📝 Получить сценарий для ролика"
ENOUGH_BTN = "✅ Сырья достаточно"
MAIN_KB = ReplyKeyboardMarkup([[KeyboardButton(NEW_BTN)]], resize_keyboard=True)
COLLECT_KB = ReplyKeyboardMarkup([[KeyboardButton(LOOK_BTN)], [KeyboardButton(GET_SCRIPT_BTN)],
                                  [KeyboardButton(NEW_BTN)]], resize_keyboard=True)
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
        [InlineKeyboardButton("🖊 Общие правки (ко всему ролику)", callback_data="edit:all")],
        [InlineKeyboardButton("🎬 Собрать финальный ролик", callback_data="final")]])


def _edit_where(n) -> str:
    """Куда правка: 'all' → ко всему ролику, иначе к части N."""
    return "ко всему ролику" if str(n) == "all" else f"к части {n}"


def _retry_kb():
    """Кнопка «продолжить/повторить последнее действие» — показываем при ошибке."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Продолжить предыдущее действие", callback_data="retry")]])


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
        f"1️⃣ Жми «{NEW_BTN}» → выбери ТИП → дай РОЛИКУ имя.\n"
        "2️⃣ Кидай СЫРЬЁ (видео/фото) — всё хранится под именем ролика, повторно "
        "грузить и анализировать не надо. Плюс ТЗ (текст/голос).\n"
        f"3️⃣ Жми «{GET_SCRIPT_BTN}» — Opus напишет виральный сценарий твоим голосом.\n"
        "4️⃣ Утверждаешь → Claude САМ посмотрит клипы, разложит кадр на фразу, "
        "соберёт ролик и пришлёт 3 частями.\n"
        "5️⃣ Правишь части голосом → «Собрать финальный ролик» → публикуй.\n\n"
        "Каждый ролик — своя папка по имени (без путаницы).",
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
    b["stage"] = "await_name"                 # сначала — имя ролика
    await cq.answer(f"Тип: {reel_types.title(key)}")
    try:
        await cq.message.edit_text(f"✅ Тип: {reel_types.title(key)}\n{reel_types.hint(key)}")
    except Exception:
        pass
    existing = ""
    projs = _list_projects()
    if projs:
        existing = ("\n\nИли продолжи существующий (пришли то же имя):\n"
                    + "\n".join(f"• {p.replace('_', ' ')}" for p in projs[:12]))
    await client.send_message(
        cq.message.chat.id,
        "📝 Как назовём этот ролик? Пришли название одним сообщением "
        "(например «День 1» или «Про сосиски»).\n"
        "Всё сырьё, что зальёшь, я сложу под этим именем и буду хранить — "
        "повторно грузить и анализировать не придётся." + existing)


def _clips_summary(clips) -> str:
    lines = []
    for c in clips[:20]:
        typ = "фото" if c.get("is_image") else f"видео {c.get('dur', 0):.0f}с"
        desc = (c.get("desc") or c.get("kind", "")).strip()
        face = " · лицо" if c.get("has_face") else ""
        lines.append(f"• {desc} ({typ}{face})")
    if len(clips) > 20:
        lines.append(f"…и ещё {len(clips) - 20}")
    return "\n".join(lines)


async def _look_footage(b, m, quiet=False):
    """Claude смотрит сырьё ОДИН раз (кэш _shots.json) и запоминает в b['clips']."""
    if b.get("clips"):
        return b["clips"]                       # уже смотрел — не тратим API повторно
    if not (shots and os.environ.get("OPENROUTER_API_KEY")) or not b.get("files"):
        return []
    status, state, stop, task = await _live(m, f"👁 Смотрю сырьё ({len(b['files'])} шт.)…")
    loop = asyncio.get_event_loop()
    try:
        clips = await loop.run_in_executor(
            None, lambda: shots.analyze(b["job"], status_cb=lambda t: state.update(stage=t)))
    finally:
        stop.set()
        await task
    b["clips"] = clips or []
    if not clips:
        await status.edit_text("Не смог посмотреть сырьё (нет ключа/сети/клипов).")
        return []
    if quiet:
        await status.delete()
    else:
        await status.edit_text("👁 Посмотрел сырьё, вот что вижу:\n\n" + _clips_summary(clips)
                               + f"\n\nТеперь дай ТЗ (текст/голос) — и жми «{GET_SCRIPT_BTN}».")
    return clips


PROJECTS_DIR = os.path.join(HERE, "library", "projects")   # именованные ролики (сырьё хранится)
PUBLISHED_LOG = os.path.join(HERE, "library", "published.jsonl")
_last_reel = {}   # chat_id → {name, type} последнего собранного ролика (для архивации)


def _dir_size(d):
    total = 0
    for root, _, files in os.walk(d):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total


def _publish_archive(name, rtype):
    """Опубликован → в архив: освобождаем место (удаляем папку проекта), пишем в лог.
    Финальный ролик хранится отдельно (library/<тип>/out), он не трогается."""
    src = os.path.join(PROJECTS_DIR, _safe_name(name or ""))
    freed = _dir_size(src) if os.path.isdir(src) else 0
    tz = []
    try:
        tz = json.load(open(os.path.join(src, "_tz.json"), encoding="utf-8")) or []
    except Exception:
        tz = []
    try:
        os.makedirs(os.path.dirname(PUBLISHED_LOG), exist_ok=True)
        with open(PUBLISHED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M"), "name": name,
                                "type": rtype or "", "tz": tz}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    shutil.rmtree(src, ignore_errors=True)
    return freed


@app.on_callback_query(filters.regex(r"^publish$"))
async def cb_publish(client, cq):
    if not _cq_allowed(cq):
        return
    info = _last_reel.get(cq.message.chat.id)
    if not info or not info.get("name"):
        await cq.answer("Нет ролика для архива", show_alert=True)
        return
    freed = _publish_archive(info["name"], info.get("type"))
    await cq.answer("В архив ✅")
    try:
        await cq.message.edit_text(
            f"📦 «{info['name']}» опубликован и убран в архив. Освободил ~{human(freed)}. "
            "Финальный ролик и разбор через 6ч сохранены.")
    except Exception:
        pass
    _last_reel.pop(cq.message.chat.id, None)


def _safe_name(s, default="reel"):
    """Имя ролика → безопасное имя папки (буквы/цифры/пробелы → _). Латиница+кириллица."""
    s = re.sub(r"[^\w\sа-яёА-ЯЁ-]", "", (s or "").strip(), flags=re.U)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s[:60] or default


def _project_dir(name: str) -> str:
    d = os.path.join(PROJECTS_DIR, _safe_name(name))
    os.makedirs(d, exist_ok=True)
    return d


def _project_files(d: str) -> list:
    out = []
    try:
        for f in sorted(os.listdir(d)):
            if f.startswith("_"):
                continue
            if os.path.splitext(f)[1].lower() in (VIDEO_EXT | IMAGE_EXT):
                out.append(os.path.join(d, f))
    except Exception:
        pass
    return out


def _list_projects() -> list:
    try:
        return [n for n in sorted(os.listdir(PROJECTS_DIR))
                if os.path.isdir(os.path.join(PROJECTS_DIR, n))]
    except Exception:
        return []


async def _set_name(b, m, name):
    """Задать имя ролика: папка-проект, подхватить уже залитое сырьё, перейти к сбору."""
    b["name"] = name.strip()[:60]
    b["job"] = _project_dir(b["name"])
    b["files"] = _project_files(b["job"])       # уже залитое раньше сырьё — подхватываем
    b["tz_list"] = _load_proj_tz(b)             # и ранее данные ТЗ этого ролика
    b["tz_count"] = len(b["tz_list"])
    b["brief"] = " ".join(b["tz_list"])
    b["clips"] = []
    b["stage"] = "collect"
    cnt = len(b["files"])
    ntz = len(b["tz_list"])
    have = (f"📁 В этом ролике уже {cnt} файлов сырья"
            + (f" и {ntz} ТЗ (посмотреть/удалить — /tz)" if ntz else "") + ". " if cnt or ntz else "")
    await m.reply(
        f"✅ Ролик «{b['name']}» ({reel_types.title(b.get('type') or reel_types.DEFAULT)}).\n"
        + have +
        "Кидай сырьё (просто файлы, подписывать не надо) — всё складываю в этот ролик и храню. "
        "Один и тот же клип повторно не анализирую.\n\n"
        f"Дальше: «{LOOK_BTN}» → ТЗ (+ссылка-референс) → «{GET_SCRIPT_BTN}».\n"
        "🔥 На «Получить сценарий» я сам зайду в TrendSee (свежие тренды) и учту их в сценарии.",
        reply_markup=COLLECT_KB)


async def _uploads_done(client, chat_id):
    """Когда загрузка утихла — показать «загружено N» + кнопку «посмотри сырьё»."""
    try:
        await asyncio.sleep(DEBOUNCE)
    except asyncio.CancelledError:
        return
    b = baskets.get(chat_id)
    if not b or not b.get("files") or b.get("stage") != "collect":
        return
    n = len(b["files"])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(LOOK_BTN, callback_data="look")]])
    await client.send_message(
        chat_id, f"📥 Загружено {n} файл(ов) в ролик «{b.get('name') or '—'}». "
        "Всё сырьё принято — жми, посмотрю его:", reply_markup=kb)


def _schedule_uploads_done(client, chat_id):
    b = baskets.get(chat_id)
    if not b:
        return
    t = b.get("_upl_timer")
    if t and not t.done():
        t.cancel()
    b["_upl_timer"] = asyncio.create_task(_uploads_done(client, chat_id))


async def _look_and_propose(client, b, m):
    """Claude смотрит сырьё → заходит в TrendSee → даёт свой вариант ролика (до ТЗ)."""
    if not b.get("files"):
        await m.reply("Сначала кинь сырьё (видео/фото) — потом посмотрю.")
        return
    if not (shots and os.environ.get("OPENROUTER_API_KEY")):
        await m.reply("Для просмотра сырья нужен OPENROUTER_API_KEY в montage/.env.")
        return
    b["clips"] = []
    clips = await _look_footage(b, m, quiet=True)     # анализ (без лишнего текста)
    if not clips:
        return
    have_ts = bool(trendsee and trendsee.available())
    trends = ""
    if have_ts:
        status, state, stop, task = await _live(m, "🔥 Захожу в TrendSee — смотрю, что залетает в нише…")
        loop = asyncio.get_event_loop()
        try:
            trends = await loop.run_in_executor(None, lambda: trendsee.digest())
        finally:
            stop.set()
            await task
        line = trendsee.status_line() if trends else "🔥 TrendSee: свежих трендов не пришло (проверь доступ)."
        await status.edit_text(line)          # ВИДИМЫЙ подробный статус проверки TrendSee
    else:
        await m.reply("ℹ️ TrendSee не подключён (TRENDSEE_EMAIL/PASSWORD в .env) — придумаю без трендов.")
    st2, s2, stop2, task2 = await _live(m, "💡 Придумываю вариант под ролик (кадры + тренды)…")
    loop = asyncio.get_event_loop()
    rt = b.get("type") or reel_types.DEFAULT
    footage = shots.catalog_text(clips) if shots else ""
    try:
        prop = ((await loop.run_in_executor(None, lambda: scriptwriter.propose(footage, trends, rt)))
                if scriptwriter else "")
    finally:
        stop2.set()
        await task2
    b["proposal"] = prop
    b["stage"] = "collect"
    txt = "👁 Вот что вижу в сырье:\n" + _clips_summary(clips)
    if prop:
        txt += ("\n\n💡 МОЙ ВАРИАНТ под ролик (учёл кадры + тренды) — на что опереться:\n\n" + prop)
    txt += (f"\n\nТеперь дай ТЗ (текст/голос) — согласись с моим вариантом или скажи по-своему. "
            f"Потом «{GET_SCRIPT_BTN}».")
    try:
        await st2.edit_text(txt[:4090])
    except Exception:
        await m.reply(txt[:4090])


@app.on_message(filters.regex(f"^{re.escape(LOOK_BTN)}$"))
async def look_btn(client, m: "Message"):
    if not allowed(m):
        return
    await _look_and_propose(client, _basket(m.chat.id), m)


@app.on_callback_query(filters.regex(r"^look$"))
async def cb_look(client, cq):
    if not _cq_allowed(cq):
        return
    await cq.answer("Смотрю сырьё…")
    await _look_and_propose(client, _basket(cq.message.chat.id), cq.message)


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
    b["last_action"] = "make_script"
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
        # Claude смотрит сырьё 1 раз (кэш) — сценарий ляжет на реальные кадры
        footage = ""
        if b.get("clips"):
            footage = shots.catalog_text(b["clips"]) if shots else ""
        elif shots and os.environ.get("OPENROUTER_API_KEY"):
            state["stage"] = "👁 Смотрю сырьё, чтобы сценарий лёг на кадры…"
            clips = await loop.run_in_executor(
                None, lambda: shots.analyze(b["job"], status_cb=lambda t: state.update(stage=t)))
            b["clips"] = clips or []
            footage = shots.catalog_text(clips) if clips else ""
        # тренды «что заходит у других» (TrendSee) — если подключён
        trends = ""
        if trendsee and trendsee.available():
            state["stage"] = "🔥 Смотрю тренды: что заходит у других (TrendSee)…"
            trends = await loop.run_in_executor(None, lambda: trendsee.digest())
            if trends:
                try:
                    await m.reply(trendsee.status_line())   # видимый статус проверки
                except Exception:
                    pass
        state["stage"] = "🧠 Захожу в панель — работа над ошибками…"
        await asyncio.sleep(0.4)
        state["stage"] = "✍️ Пишу виральный сценарий (тренды + сырьё + ТЗ + прошлые ролики, Opus)…"
        rt = b.get("type") or reel_types.DEFAULT       # ключ формата → механики формата
        ref = b.get("reference", "")
        script = await loop.run_in_executor(
            None, lambda: scriptwriter.write_script(b["brief"], tr, rt, footage=footage,
                                                    reference=ref, trends=trends))
    finally:
        stop.set()
        await task
    if not script:
        why = getattr(scriptwriter, "LAST_ERROR", "") or "нет ответа от OpenRouter"
        await status.edit_text(f"❌ Сценарий не собрался.\nПричина: {why}",
                               reply_markup=_retry_kb())
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


async def _polish(b, out, vid, gray, rtype, sf, loop):
    """Авто-работа над ошибками: пока ролик слабоват — усиливаем сценарий+монтаж по
    разбору и пересобираем. Держим ЛУЧШУЮ версию. Меняет b['reel'] и b['previral'].
    → (кол-во проходов, стартовый балл, финальный балл)."""
    best_reel, best_v = b["reel"], (b.get("previral") or {})
    best_score = best_v.get("score", 0) or 0
    start_score = best_score
    cur_v = best_v
    passes = 0
    for it in range(POLISH_MAX):
        score = cur_v.get("score", 0) or 0
        fixes = (cur_v.get("weak_spots") or []) + (cur_v.get("fixes") or [])
        if score >= POLISH_TARGET or not fixes:
            break
        passes += 1
        sf(f"🤖 Довожу до миллиона: усиливаю хук и монтаж (проход {it + 1}/{POLISH_MAX})…")
        improve = "УСИЛЕНИЯ ПО РАЗБОРУ (обязательно устрани эти слабые места ролика): " \
                  + "; ".join(fixes[:8])
        new_brief = (b.get("brief") or "") + "\n" + improve
        sc = await loop.run_in_executor(None, lambda nb=new_brief: scriptwriter.write_script(nb, "", rtype))
        if sc:
            b["script"] = sc
        reel = await loop.run_in_executor(
            None, lambda: factory_reel.build(b["job"], b["script"], out, vid, gray,
                                             _music_mood(b), FPS, sf, rtype))
        if not reel:
            break
        cur_v = ((await loop.run_in_executor(None, lambda r=reel: previral.check(r, b["script"], rtype)))
                 if previral else {}) or {}
        cur_score = cur_v.get("score", 0) or 0
        if cur_score >= best_score:                 # запоминаем лучшую версию
            best_reel, best_v, best_score = reel, cur_v, cur_score
    b["reel"], b["previral"] = best_reel, best_v
    return passes, start_score, best_score


async def _assemble(client, chat_id, m):
    b = baskets.get(chat_id)
    if not b or not b.get("script"):
        await m.reply("Сначала сценарий — жми «Получить сценарий».")
        return
    if not (factory_reel and eleven and eleven.have_key() and eleven.default_voice()):
        await m.reply("Для сборки нужен ElevenLabs (ELEVEN_KEY + ELEVEN_VOICE_ID) — см. VOICE-SETUP.md.")
        return
    b["last_action"] = "assemble"
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
                await status.edit_text("❌ Не собралось (озвучка). Проверь баланс ElevenLabs.",
                                       reply_markup=_retry_kb())
                return
            b["reel"] = reel
            # предиктор виральности — Claude смотрит готовый ролик глазами
            if previral and os.environ.get("OPENROUTER_API_KEY"):
                _sf("🔮 Оцениваю виральность до публикации…")
                b["previral"] = (await loop.run_in_executor(
                    None, lambda: previral.check(reel, b["script"], rtype))) or {}
                # авто-работа над ошибками: если слабовато — сам усиливаю и пересобираю
                score = (b["previral"] or {}).get("score", 0) or 0
                if score and score < POLISH_TARGET:
                    passes, s0, s1 = await _polish(b, out, vid, gray, rtype, _sf, loop)
                    if passes:
                        await client.send_message(
                            chat_id, f"🤖 Работа над ошибками: сделал {passes} проход(а), "
                            f"виральность {s0}/10 → {s1}/10. Оставил лучшую версию.")
            reel = b["reel"]
            parts_dir = os.path.join(b["job"], "_parts")   # не в сырьё проекта
            os.makedirs(parts_dir, exist_ok=True)
            parts = await loop.run_in_executor(None, lambda: factory_reel.split_three(reel, parts_dir))
            b["parts"] = parts
            b["stage"] = "review_parts"
            await status.edit_text("Готовы 3 части — глянь каждую 👇")
            for i, p in enumerate(parts):
                await client.send_video(chat_id, p, caption=f"Часть {i + 1}/3")
            if b.get("previral"):
                await client.send_message(chat_id, previral.as_text(b["previral"]))
            await client.send_message(
                chat_id, "Готово. Хочешь — правь части/общими правками, или сразу "
                "«Собрать финальный ролик».", reply_markup=_parts_kb())
        except Exception as e:
            await status.edit_text(f"❌ Ошибка сборки: {str(e)[:200]}", reply_markup=_retry_kb())
        finally:
            b["running"] = False


@app.on_callback_query(filters.regex(r"^edit:"))
async def cb_edit(client, cq):
    if not _cq_allowed(cq):
        return
    n = cq.data.split(":", 1)[1]
    b = _basket(cq.message.chat.id)
    b["await_edit"] = n
    where = _edit_where(n)
    await cq.answer(f"Правка {where}")
    tail = ("наговори/напиши, что поменять во всём ролике (хук, темп, кадры, плашки, звук)."
            if n == "all" else "что поменять именно в этой части.")
    await client.send_message(cq.message.chat.id, f"✏️ Правка {where}: {tail}")


@app.on_callback_query(filters.regex(r"^final$"))
async def cb_final(client, cq):
    if not _cq_allowed(cq):
        return
    await cq.answer("Готовлю финал…")
    await _finalize(client, cq.message.chat.id, cq.message)


@app.on_callback_query(filters.regex(r"^retry$"))
async def cb_retry(client, cq):
    """Повторить последнее действие, которое упало (сценарий/сборка/финал)."""
    if not _cq_allowed(cq):
        return
    b = baskets.get(cq.message.chat.id)
    action = (b or {}).get("last_action")
    if not action:
        await cq.answer("Нечего продолжать 🤔", show_alert=True)
        return
    labels = {"make_script": "сценарий", "assemble": "сборку", "finalize": "финал"}
    await cq.answer(f"Продолжаю {labels.get(action, '')}…")
    chat_id, m = cq.message.chat.id, cq.message
    if action == "make_script":
        await _make_script(client, chat_id, m)
    elif action == "assemble":
        await _assemble(client, chat_id, m)
    elif action == "finalize":
        await _finalize(client, chat_id, m)
    else:
        await client.send_message(chat_id, "Не знаю, что продолжить. Начни заново кнопкой.")


async def _finalize(client, chat_id, m):
    b = baskets.get(chat_id)
    if not b or not b.get("reel"):
        await m.reply("Нечего финалить — сначала собери ролик.")
        return
    if b.get("running"):
        return
    b["last_action"] = "finalize"
    reel = b["reel"]
    # если были правки — перепишем сценарий с их учётом и пересоберём
    if b.get("edits") and scriptwriter and factory_reel:
        b["running"] = True
        status = await m.reply("🎬 Вношу правки и пересобираю финал…")
        loop = asyncio.get_event_loop()
        edits_txt = "; ".join(
            (f"общая правка: {t}" if str(n) == "all" else f"часть {n}: {t}")
            for n, t in b["edits"])
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
                await status.edit_text(f"❌ Ошибка пересборки: {str(e)[:150]}",
                                       reply_markup=_retry_kb())
                return
            finally:
                b["running"] = False
        try:
            await status.delete()
        except Exception:
            pass
    rt = b.get("type") or reel_types.DEFAULT
    reel_types.log_reel(rt, b.get("brief") or "", reel)
    await client.send_video(chat_id, reel,
        caption="✅ ФИНАЛЬНЫЙ РОЛИК — голос + субтитры + музыка под настроение (уже в ролике).\n"
                "Залей в Instagram — панель подтянет статистику, через 6ч будет разбор.",
        reply_markup=MAIN_KB)
    _last_reel[chat_id] = {"name": b.get("name"), "type": rt}
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "✅ Опубликовано → в архив (освободить место)", callback_data="publish")]])
    await client.send_message(chat_id, "Как выложишь в Инсту — жми кнопку, уберу ролик в архив "
                              "(освобожу место, из списка пропадёт).", reply_markup=kb)
    baskets.pop(chat_id, None)


def _basket(chat_id):
    b = baskets.get(chat_id)
    if not b:
        b = baskets[chat_id] = {"files": [], "job": tempfile.mkdtemp(prefix="tg_job_"),
                                "brief": "", "status": None, "running": False,
                                "type": None,             # тип ролика (кнопкой), None = по умолчанию
                                "name": None,             # имя ролика (проект-папка с сырьём)
                                "stage": None,            # await_name / collect / review_script / …
                                "await_edit": None,       # ждём правку к части N (голосом/текстом)
                                "tz_count": 0,            # сколько ТЗ принято
                                "tz_list": [],            # тексты всех ТЗ по этому ролику (/tz)
                                "clips": [],              # что Claude увидел в сырье (смотрит 1 раз)
                                "reference": "",          # контент по ссылке-референсу из ТЗ
                                "last_action": None,      # последнее действие — для кнопки «повторить»
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
    if b.get("stage") == "await_name":
        await m.reply("Сначала назови ролик — пришли название одним сообщением, потом кидай сырьё.")
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
        _add_tz(b, m.chat.id, m.caption.strip(), "подпись")
    # всё сырьё складывается в ПАПКУ РОЛИКА (b['job'] = проект по имени) и хранится там
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
        b["clips"] = []                       # новое сырьё — пересоберём каталог (анализ из кэша)
    if b.get("stage") == "add_more":
        await _prompt(b, m)
        return
    n = len(b["files"])
    await _say(b, m, f"✅ Добавлено в ролик «{b.get('name') or '—'}»: {n} файл(ов)…")
    _schedule_uploads_done(client, m.chat.id)   # когда загрузка утихнет — кнопка «посмотри сырьё»


TZ_LOG = os.path.join(HERE, "library", "tz_history.jsonl")   # история ТЗ (gitignored)


def _save_tz(chat_id, rtype, text, kind):
    """Сохранить ТЗ на диск, чтобы не терялось при перезапуске бота."""
    try:
        os.makedirs(os.path.dirname(TZ_LOG), exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M"), "chat": chat_id,
               "type": rtype, "kind": kind, "text": text}
        with open(TZ_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _proj_tz_path(b):
    j = b.get("job")
    return os.path.join(j, "_tz.json") if j else None


def _save_proj_tz(b):
    """Сохранить ТЗ ролика в его папку-проект (видно и можно удалять по /tz)."""
    p = _proj_tz_path(b)
    if not p:
        return
    try:
        json.dump(b.get("tz_list", []), open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_proj_tz(b):
    p = _proj_tz_path(b)
    try:
        return json.load(open(p, encoding="utf-8")) or []
    except Exception:
        return []


def _add_tz(b, chat_id, text, kind):
    """ТЗ в текущий ролик: в бриф, в счётчик, в список, в проект и в общий лог."""
    b["brief"] = (b["brief"] + " " + text).strip() if b["brief"] else text
    b["tz_count"] = b.get("tz_count", 0) + 1
    b.setdefault("tz_list", []).append(text)
    _save_proj_tz(b)                          # ТЗ хранятся внутри проекта ролика
    _save_tz(chat_id, b.get("type") or "", text, kind)


async def _capture_link(m, b, text):
    """Если в ТЗ есть ссылка — прочитать её как референс-ориентир (учтётся в сценарии)."""
    if not weblink:
        return
    url = weblink.find_url(text)
    if not url:
        return
    note = await m.reply("🔗 Открываю ссылку-референс…")
    try:
        loop = asyncio.get_event_loop()
        ref = await loop.run_in_executor(None, lambda: weblink.fetch(url))
    except Exception:
        ref = ""
    if ref:
        b["reference"] = ref
        await note.edit_text("🔗 Взял ссылку как референс-ориентир (учту в сценарии):\n\n"
                             + ref[:350])
    else:
        await note.edit_text("🔗 Ссылку не смог прочитать — учту её как обычный текст ТЗ.")


def _recent_tz(n=15):
    try:
        lines = open(TZ_LOG, encoding="utf-8").read().splitlines()[-n:]
    except Exception:
        return ""
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
            tp = f" · {r['type']}" if r.get("type") else ""
            out.append(f"[{r.get('ts', '')}{tp}] {r.get('text', '')[:200]}")
        except Exception:
            pass
    return "\n".join(out)


@app.on_message(filters.command("trends"))
async def cmd_trends(client, m: "Message"):
    """Собрать банк трендов по 500+ ключам (фоном) — сценарии станут учитывать тренды."""
    if not allowed(m):
        return
    if not (trendsee and trendsee.available()):
        await m.reply("Сначала подключи TrendSee: TRENDSEE_EMAIL/PASSWORD (или TRENDSEE_TOKEN) "
                      "в montage/.env.")
        return
    if not trendsee_harvest:
        await m.reply("Модуль банка трендов недоступен.")
        return
    n = len(trendsee_harvest.load_keywords())
    status = await m.reply(f"🔥 Собираю банк трендов по {n} ключам… это несколько минут, "
                           "ботом пока можно пользоваться.")
    loop = asyncio.get_event_loop()

    def _cb(t):
        try:
            asyncio.run_coroutine_threadsafe(status.edit_text(t), loop)
        except Exception:
            pass
    try:
        bank = await loop.run_in_executor(None, lambda: trendsee_harvest.harvest(status_cb=_cb))
    except Exception as e:
        await status.edit_text(f"❌ Банк не собрался: {str(e)[:150]}")
        return
    if bank.get("count"):
        await status.edit_text(f"✅ Банк трендов готов: {bank['count']} топ-роликов по "
                               f"{bank['keywords']} ключам. Теперь сценарии учитывают их.")
    else:
        await status.edit_text("Тренды не собрались — проверь доступ TrendSee (логин/пароль).")


def _tz_kb(lst):
    rows = [[InlineKeyboardButton(f"🗑 Удалить #{i + 1}", callback_data=f"deltz:{i}")]
            for i in range(len(lst))]
    return InlineKeyboardMarkup(rows) if rows else None


@app.on_message(filters.command("tz"))
async def show_tz(_, m: "Message"):
    if not allowed(m):
        return
    b = baskets.get(m.chat.id)
    lst = (b or {}).get("tz_list") or []
    if lst:
        body = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lst))
        name = (b or {}).get("name") or "текущий"
        await m.reply(f"📋 ТЗ ролика «{name}» ({len(lst)} шт.) — можно удалять:\n\n{body}",
                      reply_markup=_tz_kb(lst))
        return
    hist = _recent_tz()
    if hist:
        await m.reply("📋 Последние ТЗ (из общей истории):\n\n" + hist)
    else:
        await m.reply("Пока нет ТЗ по этому ролику. Кидай ТЗ боту — они появятся здесь "
                      "(хранятся внутри ролика, /tz покажет).")


@app.on_callback_query(filters.regex(r"^deltz:"))
async def cb_deltz(client, cq):
    if not _cq_allowed(cq):
        return
    b = baskets.get(cq.message.chat.id)
    lst = (b or {}).get("tz_list") or []
    try:
        i = int(cq.data.split(":", 1)[1])
    except ValueError:
        i = -1
    if not (0 <= i < len(lst)):
        await cq.answer("Уже удалено")
        return
    lst.pop(i)
    b["tz_count"] = len(lst)
    b["brief"] = " ".join(lst)
    _save_proj_tz(b)
    await cq.answer("Удалил ✅")
    if lst:
        body = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(lst))
        await cq.message.edit_text(f"📋 ТЗ ({len(lst)} шт.) — можно удалять:\n\n{body}",
                                   reply_markup=_tz_kb(lst))
    else:
        await cq.message.edit_text("📋 ТЗ по ролику пусто. Кидай новые.")


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
    if b.get("stage") == "await_name":            # имя ролика — голосом
        await note.delete()
        await _set_name(b, m, text)
        return
    if b.get("await_edit"):                       # правка к части (голосом)
        n = b["await_edit"]
        b["edits"].append((n, text))
        b["await_edit"] = None
        await note.delete()
        await m.reply(f"✏️ Правка {_edit_where(n)} принята: «{text[:80]}».\n"
                      "Ещё правки — жми кнопку, или собери финал:", reply_markup=_parts_kb())
        return
    if _is_go(text) and b["files"]:
        await note.delete()
        await _process_basket(client, m.chat.id)
        return
    _add_tz(b, m.chat.id, text, "голос")
    await note.delete()
    if not b["files"]:
        await m.reply(f"📝 ТЗ #{b['tz_count']} принято (голос): «{text[:60]}».\n"
                      "Пришли исходники (видео/фото).")
    else:
        await _prompt(b, m)


@app.on_message(filters.text & ~filters.command(["go", "start", "tz", "new", "trends"]))
async def on_text(client, m: "Message"):
    if not allowed(m):
        return
    b = _basket(m.chat.id)
    if b["running"]:
        return
    text = (m.text or "").strip()
    if b.get("stage") == "await_name":            # имя ролика — текстом
        await _set_name(b, m, text)
        return
    if b.get("await_edit"):                       # правка к части (текстом)
        n = b["await_edit"]
        b["edits"].append((n, text))
        b["await_edit"] = None
        await m.reply(f"✏️ Правка {_edit_where(n)} принята: «{text[:80]}».\n"
                      "Ещё правки — жми кнопку, или собери финал:", reply_markup=_parts_kb())
        return
    if _is_go(text) and b["files"]:
        await _process_basket(client, m.chat.id)
        return
    _add_tz(b, m.chat.id, text, "текст")
    await _capture_link(m, b, text)               # ссылка в ТЗ → референс-ориентир
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
