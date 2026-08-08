#!/usr/bin/env python3
"""AI-режиссёр: ТЗ автора + расшифровка речи → настройки ролика (через OpenRouter).

Возвращает dict с настройками, которые умеет применить движок:
  grayscale (bool), hook (короткий цепляющий хук в начало).
Без ключа/при ошибке → None (бот откатывается на разбор по ключевым словам).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request

MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

SYS = (
    "Ты — режиссёр коротких вертикальных Reels для русскоязычного эксперта по продажам "
    "и бизнесу. По ТЗ автора и расшифровке его речи верни НАСТРОЙКИ монтажа СТРОГО в JSON, "
    "без пояснений вне JSON. Поля:\n"
    '- "grayscale": true/false — чёрно-белый грейд (true, если автор просит ч/б, монохром, '
    "серый или явно мотивационный «нуар»; иначе false).\n"
    '- "hook": строка до 5 слов ЗАГЛАВНЫМИ — цепляющий хук в начало ролика, по смыслу речи и ТЗ '
    "(без кавычек, без эмодзи). Если хук не нужен — пустая строка.\n"
    '- "reason": одна короткая фраза, почему такие настройки.'
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
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://platform.systemop.top", "X-Title": "OP Reels Director"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        cfg = json.loads(r["choices"][0]["message"]["content"])
        hook = (cfg.get("hook") or "").strip().strip('"').strip()
        return {
            "grayscale": bool(cfg.get("grayscale")),
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
    print(json.dumps(direct(ap.parse_args().brief, ap.parse_args().transcript),
                     ensure_ascii=False, indent=2))
