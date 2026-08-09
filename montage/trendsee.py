#!/usr/bin/env python3
"""TrendSee: тренды «что заходит у других» → сценаристу как ориентир под вирал.

Перед сценарием тянем из TrendSee реальные залетевшие ролики в нише (хук + просмотры
+ виральный коэффициент) и даём Claude: разбери, ПОЧЕМУ зашло, и примени механику,
не копируя дословно.

API: https://api.trendsee.io/api/v1 — авторизация Bearer-токеном, поиск
GET /posts/for-you. Настройка в montage/.env (без доступа модуль молча выключен):
  TRENDSEE_TOKEN          — готовый токен (или пара ниже, чтобы логиниться самим)
  TRENDSEE_EMAIL / TRENDSEE_PASSWORD   — логин/пароль TrendSee
  TRENDSEE_QUERY          — ниша (напр. «отдел продаж бизнес РОП»)
  TRENDSEE_SOCIAL_TYPE    — instagram | tiktok (опц.)
  TRENDSEE_LAST_DAYS      — окно, дней (по умолчанию 14)
  TRENDSEE_MIN_VIEWS      — порог просмотров (опц., напр. 100000)
  TRENDSEE_LIMIT          — сколько тянуть (>10, по умолчанию 36)
Только стандартная библиотека.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
from datetime import date, timedelta
from urllib.parse import urlencode

API_URL = os.environ.get("TRENDSEE_API_URL", "https://api.trendsee.io/api/v1")
QUERY = os.environ.get("TRENDSEE_QUERY", "")
_CONFIG = os.path.expanduser(
    os.environ.get("TRENDSEE_CONFIG", "~/.config/trendsee/config.json"))
_token_cache: str | None = None


def _saved_token() -> str | None:
    try:
        return json.load(open(_CONFIG, encoding="utf-8")).get("access_token") or None
    except Exception:
        return None


def _login() -> str | None:
    email = os.environ.get("TRENDSEE_EMAIL")
    password = os.environ.get("TRENDSEE_PASSWORD")
    if not (email and password):
        return None
    body = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL.rstrip('/')}/auth/login", data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=30))
        return r.get("access_token") or None
    except Exception as e:
        sys.stderr.write(f"[trendsee.login] {type(e).__name__}: {str(e)[:150]}\n")
        return None


def _token() -> str | None:
    global _token_cache
    if _token_cache:
        return _token_cache
    _token_cache = (os.environ.get("TRENDSEE_TOKEN") or _saved_token() or _login())
    return _token_cache


def available() -> bool:
    return bool(os.environ.get("TRENDSEE_TOKEN") or _saved_token()
                or (os.environ.get("TRENDSEE_EMAIL") and os.environ.get("TRENDSEE_PASSWORD")))


def _find_items(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in ("items", "posts", "data", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def fetch(query: str = "", limit: int = 0, timeout: int = 30) -> list[dict]:
    """Поиск залетевших роликов в нише. → [{caption,views,viral,er,url,social}] или []."""
    token = _token()
    if not token:
        return []
    limit = limit or int(os.environ.get("TRENDSEE_LIMIT", "36"))
    last_days = int(os.environ.get("TRENDSEE_LAST_DAYS", "14"))
    params = {
        "query": (query or QUERY) or None,
        "limit": max(11, limit),                       # API требует > 10
        "personal": "true",
        "anomaly": "false",
        "min_date": (date.today() - timedelta(days=last_days)).isoformat(),
        "max_date": date.today().isoformat(),
    }
    if os.environ.get("TRENDSEE_SOCIAL_TYPE"):
        params["social_type"] = os.environ["TRENDSEE_SOCIAL_TYPE"]
    if os.environ.get("TRENDSEE_MIN_VIEWS"):
        params["min_views"] = os.environ["TRENDSEE_MIN_VIEWS"]
    params = {k: v for k, v in params.items() if v is not None}
    url = f"{API_URL.rstrip('/')}/posts/for-you?" + urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "Authorization": f"Bearer {token}",
        "User-Agent": "op-reels/1.0"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception as e:
        sys.stderr.write(f"[trendsee.fetch] {type(e).__name__}: {str(e)[:150]}\n")
        return []
    out = []
    for it in _find_items(data):
        cap = " ".join(str(it.get("caption") or "").split())
        if not cap:
            continue
        out.append({
            "caption": cap[:200],
            "views": it.get("play_count") or it.get("view_count"),
            "viral": it.get("viral_coef") or it.get("subscribers_viral_coef"),
            "er": it.get("er"),
            "url": it.get("social_url"),
            "social": it.get("social_type"),
        })
    out.sort(key=lambda x: (x.get("viral") or 0, x.get("views") or 0), reverse=True)
    return out


def digest(query: str = "", top: int = 12) -> str:
    """Текст-ориентир для сценариста из реальных трендов. "" — если пусто/не настроено."""
    items = fetch(query)
    if not items:
        return ""
    lines = ["ЧТО ЗАХОДИТ У ДРУГИХ СЕЙЧАС (реальные залетевшие ролики из TrendSee — разбери, "
             "ПОЧЕМУ зашло: хук, структура, крючок удержания; примени механику, НЕ копируя "
             "дословно и НЕ выдумывая фактов о продукте):"]
    for it in items[:top]:
        bits = []
        if it.get("views"):
            bits.append(f"{int(it['views']):,} просм".replace(",", " "))
        if it.get("viral"):
            bits.append(f"вирал ×{float(it['viral']):.0f}")
        if it.get("er"):
            bits.append(f"ER {float(it['er']) * 100:.1f}%")
        meta = (" [" + ", ".join(bits) + "]") if bits else ""
        lines.append(f'- «{it["caption"]}»{meta}')
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="TrendSee: тренды под вирал")
    ap.add_argument("--query", default="")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    if not available():
        print("не настроено: задай TRENDSEE_TOKEN (или TRENDSEE_EMAIL+TRENDSEE_PASSWORD) в montage/.env")
    else:
        d = digest(a.query, a.top)
        print(d or "тренды не пришли (проверь токен/нишу/доступ)")
