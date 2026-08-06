#!/usr/bin/env python3
"""Подбор стоковых видео в тему через Pexels API (подход MoneyPrinterTurbo, 72K⭐).

По ключевому слову из речи качает вертикальный клип для b-roll вставок
(«наслоение новых кадров», «стоковые видео в тему»). Бесплатный ключ:
env PEXELS_API_KEY — получить на https://www.pexels.com/api/.

Мягкий откат: нет ключа/сети — возвращает None, пайплайн работает без стока.
"""
from __future__ import annotations
import os
import re
import sys
import urllib.parse
import urllib.request

PEXELS_KEY = os.environ.get("PEXELS_API_KEY")

# короткий русский стоп-лист для выбора ключевых слов
STOP = set("и в во не что он на я с со как а то все она так его но да ты к у же вы за бы "
           "по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли "
           "если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего "
           "ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего "
           "это этот эта эти нас про над при том этом".split())


def keywords(words, top=3):
    """Топ значимых слов из транскрипта (для запроса к стоку)."""
    freq = {}
    for w in words or []:
        t = re.sub(r"[^\wа-яё]", "", (w.get("word") if isinstance(w, dict) else w).lower())
        if len(t) >= 5 and t not in STOP:
            freq[t] = freq.get(t, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:top]]


def fetch_stock(query, out_path, orientation="portrait"):
    """Скачать вертикальный стоковый клип по запросу. → путь или None."""
    if not PEXELS_KEY:
        return None
    try:
        url = ("https://api.pexels.com/videos/search?"
               + urllib.parse.urlencode({"query": query, "orientation": orientation, "per_page": 5}))
        req = urllib.request.Request(url, headers={"Authorization": PEXELS_KEY})
        with urllib.request.urlopen(req, timeout=30) as r:
            import json
            data = json.load(r)
        best = None
        for v in data.get("videos", []):
            for f in sorted(v.get("video_files", []), key=lambda f: (f.get("height") or 0)):
                if (f.get("height") or 0) >= (f.get("width") or 0) and (f.get("height") or 0) >= 720:
                    best = f["link"]
                    break
            if best:
                break
        if not best:
            return None
        urllib.request.urlretrieve(best, out_path)
        return out_path
    except Exception as e:
        sys.stderr.write(f"[stock] {type(e).__name__}: {str(e)[:100]} — без стока\n")
        return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Скачать стоковый клип (Pexels)")
    ap.add_argument("query")
    ap.add_argument("out")
    a = ap.parse_args()
    r = fetch_stock(a.query, a.out)
    print("скачано →" + r if r else "нет ключа/результата (PEXELS_API_KEY?)")
