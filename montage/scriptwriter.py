#!/usr/bin/env python3
"""AI-сценарист виральных Reels: ТЗ автора + расшифровка сырых данных → сценарий.

Пишет сценарий на 3 части (хук / основа / финал+оффер) под русскоязычную аудиторию
с упором на УДЕРЖАНИЕ (досмотр >60%), плюс плашки-акценты и CTA. Работает через
OpenRouter (по умолчанию Claude Opus). Без ключа/баланса → None.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request

try:
    import kb  # промпт + база знаний + стиль автора из factory/
except Exception:
    kb = None

MODEL = os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-4.1"

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


def write_script(briefs, transcript: str = "", rtype_hint: str = "",
                 api_key: str | None = None, timeout: int = 180):
    """briefs — строка или список ТЗ; transcript — расшифровка сырых данных. → dict|None."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    if isinstance(briefs, (list, tuple)):
        briefs = "\n".join(f"- {b}" for b in briefs if b)
    sys_prompt = (kb.prompt("scenarist") if kb else "") or VIRALITY_PROMPT
    factory_ctx = (kb.context() if kb else "")
    user = ((factory_ctx + "\n\n" if factory_ctx else "")
            + f"ТИП РОЛИКА: {rtype_hint or 'продающий'}\n\n"
            f"ТЗ АВТОРА (может быть несколько):\n{_clip(briefs, 4000) or '(не задано)'}\n\n"
            f"РАСШИФРОВКА СЫРЫХ ДАННЫХ (речь из присланных видео, если есть):\n"
            f"{_clip(transcript, 6000) or '(нет)'}")
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": user}],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://systemop.pro", "X-Title": "OP Reels Scriptwriter"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        cfg = json.loads(r["choices"][0]["message"]["content"])
    except Exception as e:
        sys.stderr.write(f"[scriptwriter] {type(e).__name__}: {str(e)[:150]}\n")
        return None
    cards = []
    for c in (cfg.get("cards") or [])[:7]:
        if isinstance(c, dict) and c.get("headline"):
            cards.append({"label": _clip(c.get("label", ""), 40),
                          "headline": _clip(c.get("headline", ""), 40),
                          "sub": _clip(c.get("sub", ""), 60),
                          "color": c.get("color", "yellow")})
    mood = (cfg.get("music_mood") or "energetic").strip().lower()
    if mood not in ("energetic", "calm", "epic"):
        mood = "energetic"
    return {
        "hook": _clip(cfg.get("hook", ""), 80),
        "part1": _clip(cfg.get("part1", ""), 700),
        "part2": _clip(cfg.get("part2", ""), 900),
        "part3": _clip(cfg.get("part3", ""), 700),
        "cards": cards,
        "cta_word": _clip(cfg.get("cta_word", "ОП"), 30),
        "music_mood": mood,
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
