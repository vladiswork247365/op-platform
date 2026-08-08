#!/usr/bin/env python3
"""Генерация контента по наполнению сайта — Reels-сценарии в бренде «Система ОП».

Читает content/site_content.md (+ факт связи с платформой), просит модель (по умолчанию
Claude Opus через OpenRouter) написать 3 готовых сценария Reels в вирусном стиле
(джампкат, пословные субтитры бело-красные, плашки, CTA). Пишет:

  content/reels_latest.md   — свежая пачка сценариев
  content/reels_archive.md  — история (дописывается сверху с датой)

Запускается в GitHub Actions. Без OPENROUTER_API_KEY завершается мягко (код 0).
Только стандартная библиотека.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = os.environ.get("STAMP") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-opus-4.1")
KEY = os.environ.get("OPENROUTER_API_KEY")
N = int(os.environ.get("CONTENT_COUNT", "3"))

SYS = (
    "Ты — вирусный сценарист коротких вертикальных Reels для бренда «СИСТЕМА ОП» — "
    "русскоязычной платформы ИИ-контроля качества продаж (слушает 100% звонков и чатов, "
    "оценивает этапы разговора, находит риск срыва сделки, интеграция с amoCRM/Битрикс). "
    "Аудитория — собственники бизнеса и РОПы. Фирменные цвета субтитров: белый + красный.\n\n"
    f"На основе НАПОЛНЕНИЯ САЙТА ниже напиши {N} РАЗНЫХ готовых сценария Reels. Каждый строго "
    "в формате Markdown:\n"
    "### Reel N — <короткое название>\n"
    "- **Хук (0–2с):** одна цепляющая фраза\n"
    "- **Сценарий (~35–45с):** сплошной текст, который автор проговаривает на камеру, "
    "живой разговорный язык, боль → решение → доказательство → оффер\n"
    "- **Плашки-акценты:** 4–7 коротких надписей (капсом), которые всплывают по ходу\n"
    "- **B-roll:** что показать вставками (экран панели, уведомления и т.п.)\n"
    "- **CTA:** слово для комментариев и что автор пришлёт в личку\n\n"
    "Пиши по-русски, конкретно, без воды и без выдуманных цифр — опирайся только на факты "
    "с сайта. Стиль монтажа: джампкат, рез на каждую фразу."
)


def _read(path, limit=None):
    try:
        s = open(path, encoding="utf-8").read()
        return s[:limit] if limit else s
    except Exception:
        return ""


def main():
    site = _read(os.path.join(HERE, "site_content.md"), 9000)
    if len(site.strip()) < 80:
        open(os.path.join(HERE, "reels_latest.md"), "w", encoding="utf-8").write(
            f"# Контент не сгенерирован ({STAMP})\n\nНаполнение сайта пустое — "
            "проверь content/site_content.md и доступность сайта.\n")
        print("site_content.md пуст — пропускаю генерацию")
        return
    snap = _read(os.path.join(HERE, "platform_snapshot.json"))
    fact = ""
    try:
        s = json.loads(snap)
        if s.get("api_ok"):
            fact = "\n\nФакт: платформа онлайн, ИИ-мониторинг работает в реальном времени."
    except Exception:
        pass
    if not KEY:
        print("::warning::OPENROUTER_API_KEY не задан — генерация пропущена")
        open(os.path.join(HERE, "reels_latest.md"), "w", encoding="utf-8").write(
            f"# Контент не сгенерирован ({STAMP})\n\nНет OPENROUTER_API_KEY в секретах репозитория. "
            "Добавь: Settings → Secrets and variables → Actions → New repository secret.\n")
        return

    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": f"НАПОЛНЕНИЕ САЙТА:\n\n{site}{fact}"}],
        "temperature": 0.7,
        "max_tokens": 2600,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://systemop.pro", "X-Title": "SystemOP Content"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=180))
        text = r["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"::error::генерация не удалась: {type(e).__name__}: {str(e)[:160]}")
        sys.exit(1)

    header = f"# Reels-сценарии «Система ОП» — {STAMP}\n\n_Модель: {MODEL}. Источник: наполнение сайта._\n\n"
    with open(os.path.join(HERE, "reels_latest.md"), "w", encoding="utf-8") as f:
        f.write(header + text + "\n")
    # архив — дописываем сверху
    arch = os.path.join(HERE, "reels_archive.md")
    old = _read(arch)
    with open(arch, "w", encoding="utf-8") as f:
        f.write(header + text + "\n\n---\n\n" + old)
    print(f"✓ сгенерировано {N} сценариев ({len(text)} символов) моделью {MODEL}")


if __name__ == "__main__":
    main()
