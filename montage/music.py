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

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_DIR = os.path.join(HERE, "library", "music")   # твои бесплатные треки (без регистраций)
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus"}

# настроение → теги Jamendo
MOODS = {
    "energetic": "energetic,corporate,upbeat",
    "calm": "calm,inspiring,ambient",
    "epic": "epic,motivational,powerful",
}
# синонимы настроения в именах файлов локальной библиотеки
_MOOD_WORDS = {
    "energetic": ("energetic", "energy", "upbeat", "drive", "драйв", "бодр", "хайп", "phonk", "фонк"),
    "calm": ("calm", "chill", "lofi", "ambient", "спокой", "лёгк", "легк", "эмбиент"),
    "epic": ("epic", "cinematic", "powerful", "эпик", "кино", "мощ", "пафос"),
}


def have_key() -> bool:
    return bool(os.environ.get("JAMENDO_CLIENT_ID"))


def local_dir() -> str:
    os.makedirs(LOCAL_DIR, exist_ok=True)
    return LOCAL_DIR


def _local_tracks() -> list:
    d = local_dir()
    out = []
    for f in sorted(os.listdir(d)):
        if f.startswith((".", "_")):
            continue
        if os.path.splitext(f)[1].lower() in AUDIO_EXT:
            out.append(os.path.join(d, f))
    return out


def have_local() -> bool:
    return bool(_local_tracks())


def local_pick(mood: str = "energetic") -> str | None:
    """Взять трек из своей библиотеки под настроение (по имени файла), иначе — самый свежий."""
    ts = _local_tracks()
    if not ts:
        return None
    words = _MOOD_WORDS.get((mood or "").lower(), ())
    for t in ts:
        name = os.path.basename(t).lower()
        if any(w and w in name for w in words):
            return t
    return max(ts, key=os.path.getmtime)


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
