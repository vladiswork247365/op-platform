#!/usr/bin/env python3
"""AI-сценарист виральных Reels: ТЗ автора + расшифровка сырых данных → сценарий.

Пишет сценарий на 3 части (хук / основа / финал+оффер) под русскоязычную аудиторию
с упором на УДЕРЖАНИЕ (досмотр >60%), плюс плашки-акценты и CTA. Работает через
OpenRouter (по умолчанию Claude Opus). Без ключа/баланса → None.
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.error
import urllib.request

try:
    import kb  # промпт + база знаний + стиль автора из factory/
except Exception:
    kb = None
try:
    import reel_types  # виральные механики под формат
except Exception:
    reel_types = None
try:
    import lessons  # работа над ошибками: уроки из панели (reels.json)
except Exception:
    lessons = None

# Opus 4.5 — новее и в 3 раза дешевле старого 4.1 ($5/$25 vs $15/$75 за 1М).
# Хочешь дешевле для потока — поставь anthropic/claude-sonnet-4.5 в montage/.env.
MODEL = os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-4.5"

# Последняя понятная причина сбоя (её показывает бот в Телеграме вместо «проверь баланс»).
LAST_ERROR = ""


def _human_error(status: int, api_msg: str) -> str:
    """Код ответа OpenRouter + текст → понятная подсказка для Телеграма."""
    api_msg = (api_msg or "").strip()
    low = api_msg.lower()
    if status == 401 or "no auth" in low or "invalid api key" in low:
        return "Неверный OPENROUTER_API_KEY. Проверь ключ в montage/.env."
    if status == 402 or "insufficient" in low or "credit" in low:
        return f"На OpenRouter не хватает средств для этой модели ({MODEL})."
    if "data policy" in low or "no endpoints" in low or "no allowed providers" in low:
        return ("OpenRouter блокирует модель настройками приватности. Зайди на "
                "openrouter.ai/settings/privacy и включи доступ к моделям (или включи VPN).")
    if status == 404 or "not found" in low or "not a valid model" in low:
        return f"Модель «{MODEL}» недоступна на твоём аккаунте. Поменяй OPENROUTER_MODEL в montage/.env."
    if status == 429 or "rate" in low:
        return "OpenRouter ограничил частоту запросов (429). Подожди минуту и попробуй снова."
    if status:
        return f"OpenRouter вернул ошибку {status}: {api_msg[:160]}"
    return api_msg[:200] or "неизвестная ошибка сети/OpenRouter"

# ── ОБЩИЙ ВИРАЛЬНЫЙ ПРОМПТ (правится под задачу) ──
VIRALITY_PROMPT = (
    "Ты — лучший сценарист коротких вертикальных Reels для РУССКОЯЗЫЧНОЙ аудитории "
    "(собственники бизнеса и РОПы). Твоя единственная цель — чтобы ролик досматривали "
    "и репостили: удержание внимания выше 60%, сильные комментарии, шеры.\n\n"
    "ЖЁСТКИЕ ПРАВИЛА УДЕРЖАНИЯ:\n"
    "1) Первые 2 секунды решают всё — начни с ХУКА: паттерн-интеррапт, смелое заявление, "
    "боль зрителя или интрига. НИКАКИХ вступлений и «привет, меня зовут».\n"
    "2) Разговорный живой русский, обращение на «ты». Короткие рубленые фразы — под "
    "джампкат (каждая фраза = отдельный кадр/рез).\n"
    "3) Держи открытые петли: «но…», «и вот тут главное…», «夰а самое интересное…» — "
    "чтобы досмотрели до конца.\n"
    "4) Конкретика вместо воды: цифры, примеры, контраст «было/стало». Без канцелярита.\n"
    "5) Финал — чёткий оффер и ОДНО действие: слово в комментарии.\n"
    "6) Опирайся на реальные механики виральных Reels в нише продаж/бизнеса, но не "
    "выдумывай фактов о продукте — бери только из ТЗ и расшифровки.\n\n"
    "СТРУКТУРА (ровно 3 части, чтобы ролик собирался кусками):\n"
    "• part1 — ХУК + завязка (0–5с): цепляет и обещает пользу.\n"
    "• part2 — ОСНОВА: проблема → решение (продукт) → доказательство. 3–5 коротких фраз.\n"
    "• part3 — ФИНАЛ: добивка ценности + оффер + CTA.\n\n"
    "Верни СТРОГО JSON без пояснений вне JSON:\n"
    '{\n'
    '  "hook": "одна цепляющая фраза, ЗАГЛАВНЫМИ, до 8 слов",\n'
    '  "part1": "текст части 1 (что автор проговаривает на камеру), 2–3 фразы",\n'
    '  "part2": "текст части 2, 3–5 фраз",\n'
    '  "part3": "текст части 3 + оффер, 2–4 фразы",\n'
    '  "cards": [ {"label":"мелкий верх","headline":"КРУПНО 1-3 слова","sub":"→ подпись",'
    '"color":"yellow|cyan|pink|red"} ],  // 4–7 плашек-акцентов по смыслу\n'
    '  "cta_word": "СЛОВО ДЛЯ КОММЕНТОВ (например ОП)",\n'
    '  "why": "1–2 фразы: почему это зайдёт и удержит внимание"\n'
    '}'
)


def _clip(s, n):
    s = (s or "").strip()
    return s[:n]


def _parse_json(content: str):
    """Достать JSON из ответа модели: чистый JSON, ```json…```, или {…} внутри текста.

    Anthropic-модели на OpenRouter часто игнорируют response_format и оборачивают
    ответ в markdown/добавляют преамбулу — из-за этого строгий json.loads падал,
    а деньги за ответ уже списывались. Здесь парсим устойчиво.
    """
    content = (content or "").strip()
    if not content:
        return None
    if content.startswith("```"):                       # ```json … ```
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content).strip()
    try:
        return json.loads(content)
    except Exception:
        pass
    i, j = content.find("{"), content.rfind("}")         # выдернуть {…} из текста
    if 0 <= i < j:
        try:
            return json.loads(content[i:j + 1])
        except Exception:
            return None
    return None


def write_script(briefs, transcript: str = "", rtype_hint: str = "", footage: str = "",
                 reference: str = "", api_key: str | None = None, timeout: int = 180):
    """briefs — ТЗ; transcript — речь из сырья; footage — что Claude увидел в кадрах;
    reference — контент по ссылке автора (ориентир результата). → dict|None."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    if isinstance(briefs, (list, tuple)):
        briefs = "\n".join(f"- {b}" for b in briefs if b)
    sys_prompt = (kb.prompt("scenarist") if kb else "") or VIRALITY_PROMPT
    factory_ctx = (kb.context() if kb else "")
    # формат + его виральные механики (rtype_hint может быть ключом типа или названием)
    rt_title, rt_play = (rtype_hint or "продающий"), ""
    if reel_types and reel_types.valid(rtype_hint):
        rt_title = reel_types.title(rtype_hint)
        rt_play = reel_types.script_play(rtype_hint)
    fmt = f"ФОРМАТ РОЛИКА: {rt_title}\n"
    if rt_play:
        fmt += ("ВИРАЛЬНЫЕ МЕХАНИКИ ЭТОГО ФОРМАТА (выжми из формата максимум, применяй "
                "именно эти механики):\n" + rt_play + "\n")
    # работа над ошибками: перед новым сценарием учимся на прошлых роликах из панели
    work = ""
    if lessons:
        try:
            d = lessons.digest(rtype_hint if (reel_types and reel_types.valid(rtype_hint)) else "")
        except Exception:
            d = ""
        if d:
            work = ("РАБОТА НАД ОШИБКАМИ — сначала изучи свои прошлые ролики из панели и "
                    "ОБЯЗАТЕЛЬНО учти: повтори то, что заходило, и НЕ повторяй прошлых ошибок.\n"
                    + d + "\n\n")
    footage_block = ""
    if footage:
        footage_block = ("ЧТО ЕСТЬ В КАДРАХ (Claude посмотрел присланное сырьё — пиши сценарий "
                         "ПОД эти реальные кадры, чтобы картинка совпадала со словами):\n"
                         + _clip(footage, 3000) + "\n\n")
    ref_block = ""
    if reference:
        ref_block = ("РЕФЕРЕНС-ОРИЕНТИР (ссылка автора — целься в ТАКОЙ результат: разбери, "
                     "почему заходит, и повтори механику, НЕ копируя дословно):\n"
                     + _clip(reference, 2500) + "\n\n")
    user = ((factory_ctx + "\n\n" if factory_ctx else "")
            + fmt + "\n"
            + work
            + footage_block
            + ref_block
            + f"ТЗ АВТОРА (может быть несколько):\n{_clip(briefs, 4000) or '(не задано)'}\n\n"
            f"РАСШИФРОВКА СЫРЫХ ДАННЫХ (речь из присланных видео, если есть):\n"
            f"{_clip(transcript, 6000) or '(нет)'}")
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": user}],
        "temperature": 0.7,
        "max_tokens": 4000,                     # хватит на весь JSON, не обрежется
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://systemop.pro", "X-Title": "OP Reels Scriptwriter"})
    global LAST_ERROR
    LAST_ERROR = ""
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        if isinstance(r, dict) and r.get("error"):          # OpenRouter иногда шлёт ошибку в 200
            em = r["error"]
            msg = em.get("message") if isinstance(em, dict) else str(em)
            code = em.get("code") if isinstance(em, dict) else 0
            LAST_ERROR = _human_error(int(code or 0), msg)
            sys.stderr.write(f"[scriptwriter] api-error: {msg}\n")
            return None
        content = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        cfg = _parse_json(content)
        if cfg is None:
            LAST_ERROR = ("Модель ответила, но не в формате JSON (ответ пришёл, деньги "
                          "списались). Обычно лечится сменой модели в OPENROUTER_MODEL.")
            sys.stderr.write(f"[scriptwriter] bad-json: {content[:200]}\n")
            return None
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "ignore"))
            api_msg = (detail.get("error") or {}).get("message") or str(detail)
        except Exception:
            api_msg = ""
        LAST_ERROR = _human_error(e.code, api_msg)
        sys.stderr.write(f"[scriptwriter] HTTP {e.code}: {api_msg[:200]}\n")
        return None
    except Exception as e:
        LAST_ERROR = _human_error(0, f"{type(e).__name__}: {str(e)[:150]}")
        sys.stderr.write(f"[scriptwriter] {type(e).__name__}: {str(e)[:150]}\n")
        return None
    cards = []
    for c in (cfg.get("cards") or [])[:8]:
        if isinstance(c, dict) and c.get("headline"):
            try:
                at = float(c.get("at"))
                at = min(1.0, max(0.0, at))
            except (TypeError, ValueError):
                at = None
            cards.append({"label": _clip(c.get("label", ""), 40),
                          "headline": _clip(c.get("headline", ""), 40),
                          "sub": _clip(c.get("sub", ""), 60),
                          "color": c.get("color", "yellow"), "at": at})
    mood = (cfg.get("music_mood") or "energetic").strip().lower()
    if mood not in ("energetic", "calm", "epic"):
        mood = "energetic"
    pace = (cfg.get("pace") or "medium").strip().lower()
    if pace not in ("fast", "medium"):
        pace = "medium"
    v = cfg.get("voice") or {}
    def _f(x, lo, hi, d):
        try:
            return min(hi, max(lo, float(x)))
        except (TypeError, ValueError):
            return d
    voice = {"stability": _f(v.get("stability"), 0.0, 1.0, 0.4),
             "style": _f(v.get("style"), 0.0, 1.0, 0.5),
             "speed": _f(v.get("speed"), 0.7, 1.2, 1.05)}
    hl = [str(w).strip() for w in (cfg.get("highlight_words") or []) if str(w).strip()][:12]
    return {
        "hook": _clip(cfg.get("hook", ""), 80),
        "part1": _clip(cfg.get("part1", ""), 700),
        "part2": _clip(cfg.get("part2", ""), 900),
        "part3": _clip(cfg.get("part3", ""), 700),
        "cards": cards,
        "highlight_words": hl,
        "cta_word": _clip(cfg.get("cta_word", "ОП"), 30),
        "music_mood": mood,
        "grayscale": bool(cfg.get("grayscale")),
        "pace": pace,
        "voice": voice,
        "why": _clip(cfg.get("why", ""), 200),
    }


def as_text(s: dict) -> str:
    """Красиво собрать сценарий в текст для показа в Телеграме."""
    lines = [f"🎬 ХУК: {s['hook']}", "", f"1) {s['part1']}", "", f"2) {s['part2']}", "",
             f"3) {s['part3']}", ""]
    if s.get("cards"):
        lines.append("🟨 Плашки:")
        for c in s["cards"]:
            lines.append(f"  • {c['headline']}" + (f" — {c['sub']}" if c.get("sub") else ""))
        lines.append("")
    lines.append(f"📣 CTA: напиши «{s['cta_word']}» в комментах")
    if s.get("why"):
        lines.append(f"\n💡 {s['why']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AI-сценарист виральных Reels")
    ap.add_argument("brief")
    ap.add_argument("--transcript", default="")
    a = ap.parse_args()
    print(f"модель: {MODEL} | ключ: {'есть' if os.environ.get('OPENROUTER_API_KEY') else 'НЕТ'}")
    s = write_script(a.brief, a.transcript)
    print("не удалось (нет ключа/баланса/сети)" if not s else as_text(s))
