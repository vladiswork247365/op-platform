#!/usr/bin/env python3
"""Банк трендов: пройти по 500+ ключам (trend_keywords.txt), собрать топ-виральные
ролики из TrendSee, дедуп, сохранить в library/trend_bank.json.

Гоняется в ФОНЕ (кнопкой /trends в боте или руками) — а сценарист берёт из готового
банка мгновенно, без 500 запросов на каждый ролик. Обновляй раз в день.
"""
from __future__ import annotations
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trendsee  # noqa: E402

KEYWORDS_FILE = os.path.join(HERE, "trend_keywords.txt")
BANK_FILE = os.path.join(HERE, "library", "trend_bank.json")


def load_keywords(path: str | None = None) -> list[str]:
    try:
        return [ln.strip() for ln in open(path or KEYWORDS_FILE, encoding="utf-8")
                if ln.strip() and not ln.startswith("#")]
    except Exception:
        return []


def harvest(keywords: list[str] | None = None, per_keyword: int = 8, cap: int = 250,
            sleep: float = 0.25, status_cb=None) -> dict:
    """Собрать банк трендов по ключам. → {updated,count,keywords,posts}."""
    kws = keywords or load_keywords()
    if not kws or not trendsee.available():
        return {"updated": time.strftime("%Y-%m-%d %H:%M"), "count": 0, "keywords": 0, "posts": []}
    seen, posts, empties = set(), [], 0
    total = len(kws)
    for i, kw in enumerate(kws):
        try:
            items = trendsee.fetch(kw, limit=36)     # уже отсортированы по виральности
        except Exception:
            items = []
        if not items:
            empties += 1
        for it in items[:per_keyword]:
            key = (it.get("url") or it.get("caption") or "")[:120]
            if not key or key in seen:
                continue
            seen.add(key)
            rec = dict(it)
            rec["keyword"] = kw
            posts.append(rec)
        if status_cb and (i % 20 == 0 or i == total - 1):
            try:
                status_cb(f"🔥 Собираю банк трендов: {i + 1}/{total} ключей, найдено {len(posts)}…")
            except Exception:
                pass
        if empties >= 25 and not posts:              # доступа нет — не молотим впустую
            break
        time.sleep(sleep)
    posts.sort(key=lambda x: (x.get("viral") or 0, x.get("views") or 0), reverse=True)
    posts = posts[:cap]
    bank = {"updated": time.strftime("%Y-%m-%d %H:%M"), "count": len(posts),
            "keywords": len(kws), "posts": posts}
    try:
        os.makedirs(os.path.dirname(BANK_FILE), exist_ok=True)
        json.dump(bank, open(BANK_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write(f"[harvest] save: {type(e).__name__}: {e}\n")
    return bank


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Банк трендов из TrendSee по ключам")
    ap.add_argument("--keywords", default="", help="файл с ключами (по умолч. trend_keywords.txt)")
    ap.add_argument("--per-keyword", type=int, default=8)
    ap.add_argument("--cap", type=int, default=250)
    a = ap.parse_args()
    if not trendsee.available():
        print("не настроено: задай TRENDSEE_EMAIL+TRENDSEE_PASSWORD (или TRENDSEE_TOKEN) в montage/.env")
    else:
        kws = load_keywords(a.keywords or None)
        print(f"ключей: {len(kws)} — собираю (это несколько минут)…")
        bank = harvest(kws, a.per_keyword, a.cap, status_cb=lambda t: print(t))
        print(f"✅ банк: {bank['count']} топ-роликов по {bank['keywords']} ключам → {BANK_FILE}")
