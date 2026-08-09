#!/usr/bin/env python3
"""Разбор ролика после публикации: метрики → развёрнутая обратная связь по ошибкам.

Через 6 часов после публикации в Инсте Claude смотрит статистику ролика и говорит,
что сработало, где отвалилось внимание и ЧТО КОНКРЕТНО поправить в следующем ролике —
с учётом формата (виральные механики из reel_types) и того, что мы задумывали в сценарии.

Два входа:
  • analyze_text(metrics)  — метрики уже текстом/словарём (из API или панели);
  • analyze_image(path)    — скрин статистики из Инсты (Claude читает цифры глазами).

Без ключа/сети → None. Только стандартная библиотека + OpenRouter.
"""
from __future__ import annotations
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

try:
    import reel_types  # что формат должен был выжать (для сверки с фактом)
except Exception:
    reel_types = None

MODEL = os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-4.5"

SYS = (
    "Ты — жёсткий аналитик виральных вертикальных Reels (Instagram/TikTok) для "
    "русскоязычной аудитории (собственники бизнеса и РОПы). Тебе дают: формат ролика и "
    "его виральные механики, задумку сценария и ФАКТИЧЕСКУЮ статистику через ~6 часов "
    "после публикации. Задача — честно разобрать, что сработало и что нет, и дать "
    "КОНКРЕТНЫЕ правки на следующий ролик. Опирайся на реальные механики удержания: "
    "первые 2–3 сек (досмотр хука), кривая удержания, среднее время просмотра, "
    "репосты/сохранения (главный сигнал виральности), комменты, переходы в профиль/подписки.\n\n"
    "Считай ориентиры: досмотр хука <70% — слабый хук; средний досмотр <50% — провал "
    "удержания; сохранения+репосты — самый ценный сигнал; много просмотров, но мало "
    "переходов/подписок — слабый оффер/CTA. Не выдумывай цифры, которых нет.\n\n"
    "Верни СТРОГО JSON без пояснений:\n"
    '{\n'
    '  "read": "какие цифры удалось считать (кратко, через ;)",\n'
    '  "score": 1-10,               // виральный потенциал по факту\n'
    '  "hook": "оценка хука: удержал ли первые секунды и почему",\n'
    '  "retention": "где и почему отваливалось внимание",\n'
    '  "engagement": "что говорят лайки/сохранения/репосты/комменты/подписки",\n'
    '  "mistakes": ["3-6 конкретных ошибок этого ролика"],\n'
    '  "fixes": ["3-6 конкретных правок на СЛЕДУЮЩИЙ ролик под этот формат"],\n'
    '  "verdict": "1-2 фразы итог"\n'
    '}'
)


def _ctx(script: dict | None, rtype: str) -> str:
    parts = []
    if reel_types and reel_types.valid(rtype):
        parts.append(f"ФОРМАТ: {reel_types.title(rtype)}")
        sp = reel_types.script_play(rtype)
        ep = reel_types.edit_play(rtype)
        if sp:
            parts.append("Виральная механика сценария (что задумывали): " + sp)
        if ep:
            parts.append("Виральная механика монтажа (что задумывали): " + ep)
    if script:
        if script.get("hook"):
            parts.append(f'ХУК ролика: {script["hook"]}')
        body = " / ".join(s for s in (script.get("part1"), script.get("part2"),
                                      script.get("part3")) if s)
        if body:
            parts.append("Сценарий: " + body[:600])
        if script.get("cta_word"):
            parts.append(f'CTA: {script["cta_word"]}')
    return "\n".join(parts)


def _parse(content: str):
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", (content or "").strip())
    try:
        return json.loads(content)
    except Exception:
        i, j = content.find("{"), content.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(content[i:j + 1])
            except Exception:
                return None
    return None


def _call(user_content, api_key, timeout=120):
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user_content}],
        "temperature": 0.3,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://systemop.pro", "X-Title": "OP Reels Feedback"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        raw = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return _parse(raw)
    except Exception as e:
        sys.stderr.write(f"[feedback] {type(e).__name__}: {str(e)[:150]}\n")
        return None


def analyze_text(metrics, script: dict | None = None, rtype: str = "",
                 api_key: str | None = None) -> dict | None:
    """Метрики текстом/словарём → разбор. → dict|None."""
    if isinstance(metrics, dict):
        metrics = "\n".join(f"{k}: {v}" for k, v in metrics.items())
    ctx = _ctx(script, rtype)
    user = ((ctx + "\n\n" if ctx else "")
            + "ФАКТИЧЕСКАЯ СТАТИСТИКА (~6ч после публикации):\n" + str(metrics).strip())
    return _call(user, api_key)


def analyze_image(image_path: str, script: dict | None = None, rtype: str = "",
                  api_key: str | None = None) -> dict | None:
    """Скрин статистики из Инсты → Claude читает цифры глазами и разбирает. → dict|None."""
    if not os.path.exists(image_path):
        return None
    ctx = _ctx(script, rtype)
    b64 = base64.b64encode(open(image_path, "rb").read()).decode()
    content = [
        {"type": "text", "text": ((ctx + "\n\n" if ctx else "")
         + "Считай ВСЕ цифры со скрина статистики этого ролика (~6ч после публикации) "
           "и сделай разбор. Верни JSON.")},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]
    return _call(content, api_key)


def as_text(f: dict) -> str:
    """Собрать разбор в текст для Телеграма."""
    if not f:
        return "Не удалось разобрать статистику."
    out = [f"📊 РАЗБОР РОЛИКА — {f.get('score', '?')}/10", ""]
    if f.get("read"):
        out.append(f"🔎 Считал: {f['read']}")
    if f.get("hook"):
        out.append(f"🎣 Хук: {f['hook']}")
    if f.get("retention"):
        out.append(f"⏱ Удержание: {f['retention']}")
    if f.get("engagement"):
        out.append(f"❤️ Вовлечение: {f['engagement']}")
    if f.get("mistakes"):
        out.append("\n❌ Ошибки:")
        out += [f"  • {m}" for m in f["mistakes"]]
    if f.get("fixes"):
        out.append("\n✅ Что поправить в следующем:")
        out += [f"  • {x}" for x in f["fixes"]]
    if f.get("verdict"):
        out.append(f"\n💡 {f['verdict']}")
    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Разбор ролика по статистике")
    ap.add_argument("--image", help="скрин статистики из Инсты")
    ap.add_argument("--text", help="метрики текстом")
    ap.add_argument("--type", default="", help="ключ формата (product/expert/...)")
    a = ap.parse_args()
    res = (analyze_image(a.image, rtype=a.type) if a.image
           else analyze_text(a.text or "", rtype=a.type))
    print(as_text(res) if res else "нет ключа/сети/данных")
