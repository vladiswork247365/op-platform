#!/usr/bin/env python3
"""Фоновая музыка через API бесплатных треков (Jamendo, легально/Creative Commons).

Качает короткий трек под настроение и отдаёт путь к mp3. Без ключа
(JAMENDO_CLIENT_ID) — мягко возвращает None (ролик соберётся без музыки).

Ключ бесплатный: developer.jamendo.com → зарегистрируйся → Create new application →
скопируй Client ID. Впиши в montage/.env:  JAMENDO_CLIENT_ID=...
Только стандартная библиотека.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.jamendo.com/v3.0/tracks/"
KEY = os.environ.get("JAMENDO_CLIENT_ID")

# настроение → теги Jamendo
MOODS = {
    "energetic": "energetic,corporate,upbeat",
    "calm": "calm,inspiring,ambient",
    "epic": "epic,motivational,powerful",
}


def have_key() -> bool:
    return bool(os.environ.get("JAMENDO_CLIENT_ID"))


def get_track(out_path: str, mood: str = "energetic", max_dur: int = 120,
              timeout: int = 40) -> str | None:
    """Скачать короткий трек нужного настроения → путь к mp3 или None."""
    key = os.environ.get("JAMENDO_CLIENT_ID")
    if not key:
        return None
    params = {
        "client_id": key, "format": "json", "limit": "1", "order": "popularity_total",
        "audioformat": "mp32", "include": "musicinfo", "vocalinstrumental": "instrumental",
        "durationbetween": f"0_{max_dur}", "tags": MOODS.get(mood, MOODS["energetic"]),
    }
    url = API + "?" + urllib.parse.urlencode(params)
    try:
        r = json.load(urllib.request.urlopen(url, timeout=timeout))
        results = r.get("results") or []
        if not results:
            return None
        audio = results[0].get("audiodownload") or results[0].get("audio")
        if not audio:
            return None
        data = urllib.request.urlopen(audio, timeout=timeout).read()
        with open(out_path, "wb") as f:
            f.write(data)
        return out_path
    except Exception as e:
        sys.stderr.write(f"[music] {type(e).__name__}: {str(e)[:120]}\n")
        return None


if __name__ == "__main__":
    print("ключ Jamendo:", "есть" if have_key() else "НЕТ")
    p = get_track("/tmp/_music_test.mp3", "energetic")
    print("скачал:", p or "не удалось (нет ключа/сети)")
