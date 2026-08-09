#!/usr/bin/env python3
"""Режиссёр-монтажёр: Opus раскладывает КАКОЙ клип на КАКУЮ фразу.

Даёт: каталог клипов с описаниями (shots.py) + раскадровку по битам (что
говорится в каждый момент озвучки). Возвращает план: на каждый бит — лучший
клип, момент старта и движение камеры, чтобы картинка усиливала слова и держала
внимание (досмотр >60%). Это тот «виральный монтаж», где кадр совпадает со смыслом.

Без ключа/сети → plan_shots() вернёт None (оркестратор оставит подстановку кадров
по порядку). Только стандартная библиотека + OpenRouter.
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.error
import urllib.request

try:
    import reel_types  # виральные механики монтажа под формат
except Exception:
    reel_types = None

MODEL = os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-4.5"

_MOTIONS_VID = {"punch", "zoomin", "zoomout", "kick"}
_MOTIONS_IMG = {"kenburns_in", "kenburns_out"}

SYS = (
    "Ты — топовый монтажёр коротких вертикальных Reels для русскоязычной аудитории. "
    "У тебя есть УТВЕРЖДЁННЫЙ СЦЕНАРИЙ, КАТАЛОГ клипов автора (с описаниями и длиной) "
    "и РАСКАДРОВКА по битам (что говорится в каждый момент озвучки и сколько бит длится). "
    "Задача: смонтировать ролик ЛОГИЧНО под сценарий — на КАЖДЫЙ бит подобрать самый "
    "сильный клип И ЛОГИЧНО ЕГО ОБРЕЗАТЬ (выбрать в клипе осмысленный непрерывный кусок "
    "in→out), чтобы картинка совпадала со словами и держала внимание до конца.\n\n"
    "ПРАВИЛА:\n"
    "1) СЛЕДУЙ СЦЕНАРИЮ: хук цепляет, основа доказывает, финал — оффер. Кадр обязан "
    "усиливать смысл фразы именно этого бита.\n"
    "2) ОБРЕЗКА: для КАЖДОГО видео укажи in и out (секунды ВНУТРИ клипа) — самый "
    "выразительный непрерывный кусок, где происходит суть. Не бери случайный момент и не "
    "оставляй пустое/невыразительное начало. Бит длится seg секунд: если твой кусок длиннее "
    "— он проиграется чуть быстрее, короче — чуть медленнее, это норм.\n"
    "3) Бит 0 — ХУК: самый цепляющий/динамичный кадр (energy high), паттерн-интеррапт.\n"
    "4) НЕ ставь один и тот же клип на два бита подряд. Переиспользуй клип только с ДРУГИМ "
    "куском (другие in/out) и чередуй.\n"
    "5) Смысл кадра: продукт/цифра/экран → product/screen/b_roll; личное/эмоция/обращение "
    "→ talking_head.\n"
    "6) motion: для видео — punch|zoomin|zoomout|kick; для фото — kenburns_in|kenburns_out "
    "(у фото in/out не нужны).\n\n"
    "Верни СТРОГО JSON без пояснений, РОВНО по одному объекту на каждый бит:\n"
    '{"beats":[{"i":0,"file":"имя_файла_из_каталога","in":0.0,"out":2.0,'
    '"motion":"punch","reason":"кратко почему этот кадр и эта обрезка"}]}'
)


def _script_block(script: dict | None) -> str:
    if not script:
        return ""
    parts = [f'ХУК: {script.get("hook", "")}']
    for k, label in (("part1", "Часть 1 (завязка)"), ("part2", "Часть 2 (основа)"),
                     ("part3", "Часть 3 (финал+оффер)")):
        if script.get(k):
            parts.append(f"{label}: {script[k]}")
    if script.get("cta_word"):
        parts.append(f'CTA-слово: {script["cta_word"]}')
    return "УТВЕРЖДЁННЫЙ СЦЕНАРИЙ (монтируй строго под него):\n" + "\n".join(parts)


def _beats_text(beats: list[dict]) -> str:
    out = []
    for b in beats:
        tag = "ХУК, " if b.get("i") == 0 else ""
        txt = (b.get("text") or "").strip() or "(без слов)"
        out.append(f'бит {b["i"]} ({tag}{b["seg"]:.1f}с): "{txt}"')
    return "\n".join(out)


def plan_shots(beats: list[dict], clips: list[dict], script: dict | None = None,
               rtype: str = "", api_key: str | None = None, timeout: int = 150) -> dict | None:
    """→ {i: {"file","in","out","motion"}} по битам, или None (нет ключа/сети/ошибка)."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key or not beats or not clips:
        return None
    valid_files = {c["file"] for c in clips}
    by_file = {c["file"]: c for c in clips}
    sb = _script_block(script)
    play = reel_types.edit_play(rtype) if (reel_types and reel_types.valid(rtype)) else ""
    fmt = ""
    if play:
        title = reel_types.title(rtype)
        fmt = (f"ФОРМАТ: {title}\nМОНТАЖНЫЕ МЕХАНИКИ ЭТОГО ФОРМАТА (выжми из формата "
               f"максимум — темп, переходы, зумы, плашки — применяй именно их):\n{play}\n\n")
    user = (
        fmt
        + (sb + "\n\n" if sb else "")
        + "КАТАЛОГ КЛИПОВ (имя | тип и длина | вид | лицо | динамика | описание):\n"
        + "\n".join(f"- {ln}" for ln in _catalog_lines(clips))
        + "\n\nРАСКАДРОВКА (бит | что говорится | сколько длится бит):\n"
        + _beats_text(beats)
        + f"\n\nВерни план ровно на {len(beats)} бит(ов). Для КАЖДОГО видео укажи in и out "
        "(осмысленная обрезка внутри клипа)."
    )
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.5,
        "max_tokens": 2500,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://systemop.pro", "X-Title": "OP Reels Editor"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        raw = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            cfg = json.loads(raw)
        except Exception:
            i, j = raw.find("{"), raw.rfind("}")
            cfg = json.loads(raw[i:j + 1]) if 0 <= i < j else {}
    except Exception as e:
        sys.stderr.write(f"[editor] {type(e).__name__}: {str(e)[:150]}\n")
        return None

    plan = {}
    for item in (cfg.get("beats") or []):
        if not isinstance(item, dict):
            continue
        try:
            bi = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        f = (item.get("file") or "").strip()
        if f not in valid_files:
            f = _best_match(f, valid_files)
            if not f:
                continue
        info = by_file[f]

        def _num(key, default=None):
            try:
                return max(0.0, float(item.get(key)))
            except (TypeError, ValueError):
                return default

        tin = _num("in", _num("start", 0.0))          # in (или старое start)
        tout = _num("out", None)                        # осмысленная обрезка до out
        motion = (item.get("motion") or "").strip().lower()
        allowed = _MOTIONS_IMG if info["is_image"] else _MOTIONS_VID
        if motion not in allowed:
            motion = None
        plan[bi] = {"file": f, "in": tin or 0.0, "out": tout, "motion": motion}
    return plan or None


def _catalog_lines(clips: list[dict]):
    for c in clips:
        typ = "фото" if c["is_image"] else f"видео {c['dur']:.1f}с"
        face = "лицо:да" if c["has_face"] else "лицо:нет"
        tg = (" | теги: " + ", ".join(c["tags"])) if c["tags"] else ""
        yield (f'{c["file"]} | {typ} | {c["kind"]} | {face} | динамика:{c["energy"]}'
               f' | "{c["desc"]}"{tg}')


def _best_match(name: str, valid: set) -> str | None:
    """Модель могла чуть исказить имя файла — найдём ближайшее по basename."""
    name = (name or "").strip().lower()
    if not name:
        return None
    base = os.path.basename(name)
    for v in valid:
        if v.lower() == base or os.path.basename(v).lower() == base:
            return v
    for v in valid:
        if base and base in v.lower():
            return v
    return None
