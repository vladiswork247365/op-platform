#!/usr/bin/env python3
"""TrendSee: тренды «что заходит у других» → сценаристу как ориентир под вирал.

Перед сценарием тянем из TrendSee актуальные залетевшие хуки/ролики в нише и даём
Claude: разбери механику и целься в такой результат (не копируя дословно).

Настройка в montage/.env (без ключа/URL — модуль молча выключен):
  TRENDSEE_API_KEY   — ключ доступа
  TRENDSEE_URL       — полный endpoint; можно с плейсхолдерами {q} и {limit},
                       напр. https://api.trendsee.io/v1/trending?query={q}&limit={limit}
  TRENDSEE_QUERY     — ниша по умолчанию (напр. «отдел продаж бизнес РОП»)
  TRENDSEE_AUTH_HEADER  — заголовок авторизации (по умолчанию Authorization)
  TRENDSEE_AUTH_PREFIX  — префикс токена (по умолчанию "Bearer ")

Парсинг терпимый: ищем список объектов и вытаскиваем хук (caption/description/
title/hook/text) + метрику (views/plays/likes/engagement). Точную схему подгоним,
когда пришлёшь пример ответа API. Только stdlib.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.parse
import urllib.request

KEY = os.environ.get("TRENDSEE_API_KEY")
URL = os.environ.get("TRENDSEE_URL")
QUERY = os.environ.get("TRENDSEE_QUERY", "")
AUTH_HEADER = os.environ.get("TRENDSEE_AUTH_HEADER", "Authorization")
AUTH_PREFIX = os.environ.get("TRENDSEE_AUTH_PREFIX", "Bearer ")

_HOOK_KEYS = ("hook", "caption", "description", "title", "text", "name", "desc")
_METRIC_KEYS = ("views", "play_count", "plays", "view_count", "likes", "like_count",
                "engagement", "shares", "saves")


def available() -> bool:
    return bool(KEY and URL)


def _extract_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for k in ("data", "results", "items", "trends", "videos", "posts", "reels", "content"):
            v = data.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _first(d: dict, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", 0):
            return v
    return None


def fetch(query: str = "", limit: int = 10, timeout: int = 25) -> list[dict]:
    """→ [{'hook','metric'}] актуальных трендов. [] — если не настроено/ошибка."""
    if not available():
        return []
    q = urllib.parse.quote(query or QUERY or "")
    url = URL.replace("{q}", q).replace("{limit}", str(limit))
    if "{q}" not in URL and (query or QUERY) and "?" not in url:
        url += f"?query={q}"
    req = urllib.request.Request(url, headers={AUTH_HEADER: f"{AUTH_PREFIX}{KEY}",
                                               "Accept": "application/json"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception as e:
        sys.stderr.write(f"[trendsee] {type(e).__name__}: {str(e)[:150]}\n")
        return []
    out = []
    for it in _extract_items(data)[:limit]:
        hook = _first(it, _HOOK_KEYS)
        if not hook:
            continue
        out.append({"hook": str(hook).strip()[:220], "metric": _first(it, _METRIC_KEYS)})
    return out


def digest(query: str = "", limit: int = 10) -> str:
    """Текст-ориентир для сценариста. "" — если трендов нет/не настроено."""
    items = fetch(query, limit)
    if not items:
        return ""
    lines = ["ЧТО ЗАХОДИТ У ДРУГИХ СЕЙЧАС (тренды из TrendSee — разбери, ПОЧЕМУ заходит, "
             "и примени механику/структуру хука, НЕ копируя дословно):"]
    for it in items:
        m = f"  [{it['metric']}]" if it.get("metric") else ""
        lines.append(f"- {it['hook']}{m}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="TrendSee: тренды под вирал")
    ap.add_argument("--query", default="")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    if not available():
        print("не настроено: задай TRENDSEE_API_KEY и TRENDSEE_URL в montage/.env")
    else:
        d = digest(a.query, a.limit)
        print(d or "тренды не пришли (проверь URL/ключ/схему ответа)")
