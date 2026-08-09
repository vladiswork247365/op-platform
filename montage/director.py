#!/usr/bin/env python3
"""AI-режиссёр: ТЗ автора + расшифровка речи → настройки ролика (через OpenRouter).

Возвращает dict с настройками, которые умеет применить движок:
  grayscale (bool), hook (короткий цепляющий хук в начало).
Без ключа/при ошибке → None (бот откатывается на разбор по ключевым словам).
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.request

# По умолчанию — Claude Opus (умный режиссёр) через OpenRouter. Точный slug модели можно
# поменять в montage/.env строкой OPENROUTER_MODEL=... (список — на openrouter.ai/models).
MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-opus-4.5")

SYS = (
    "Ты — сильный режиссёр коротких вертикальных Reels для русскоязычного эксперта по "
    "продажам и бизнесу. Твоя задача — по ТЗ автора и расшифровке его речи принять решения "
    "по монтажу так, чтобы ролик цеплял с первой секунды и удерживал до конца. Верни ответ "
    "СТРОГО в JSON, без пояснений вне JSON. Поля:\n"
    '- "hook": строка до 5 слов ЗАГЛАВНЫМИ — мощный хук в начало (интрига/обещание/'
    "провокация по смыслу речи и ТЗ, без кавычек и эмодзи). Если хук не нужен — пустая строка.\n"
    '- "grayscale": true/false — чёрно-белый грейд (true, если автор просит ч/б, монохром, '
    "серый или явно мотивационный «нуар»; иначе false).\n"
    '- "dense": true/false — джампкат: частый рез на каждую фразу с зум-панчами. true для '
    "энергичной динамичной речи/эмоций/перечислений; false для спокойного вдумчивого тона.\n"
    '- "reason": одна короткая фраза — почему такие решения.'
)


def direct(brief: str, transcript: str = "", api_key: str | None = None, timeout: int = 40):
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    user = (f"ТЗ автора: {brief.strip() or '(не задано)'}\n\n"
            f"Расшифровка речи (начало): {transcript[:900].strip() or '(нет)'}")
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.5,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://platform.systemop.top", "X-Title": "OP Reels Director"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        content = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        m = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        try:
            cfg = json.loads(m)
        except Exception:                                # выдернуть {…} из текста
            i, j = m.find("{"), m.rfind("}")
            cfg = json.loads(m[i:j + 1]) if 0 <= i < j else {}
        hook = (cfg.get("hook") or "").strip().strip('"').strip()
        return {
            "grayscale": bool(cfg.get("grayscale")),
            "dense": bool(cfg.get("dense")),
            "hook": hook if 0 < len(hook.split()) <= 6 else "",
            "reason": (cfg.get("reason") or "").strip()[:120],
        }
    except Exception as e:
        sys.stderr.write(f"[director] недоступен ({type(e).__name__}: {str(e)[:90]})\n")
        return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AI-режиссёр: ТЗ → настройки")
    ap.add_argument("brief")
    ap.add_argument("--transcript", default="")
    a = ap.parse_args()
    print(f"модель: {MODEL}  |  ключ OpenRouter: {'есть' if os.environ.get('OPENROUTER_API_KEY') else 'НЕТ'}")
    res = direct(a.brief, a.transcript)
    if res is None:
        print("режиссёр не ответил (нет ключа / неверный slug модели / нет сети). "
              "Проверь OPENROUTER_API_KEY и OPENROUTER_MODEL в montage/.env")
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
