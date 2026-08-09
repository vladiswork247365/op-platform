#!/usr/bin/env python3
"""Трендовый звук: библиотека актуальных саундов, из которой Claude берёт под настроение.

Royalty-free музыка не даёт алго-буста. Охваты на Reels тянет ТРЕНДОВЫЙ звук. Здесь —
простой и честный механизм: ты кидаешь свежие трендовые саунды в папку
montage/library/trending/ (2 минуты — забрать с ленты трендов), а система под каждый
ролик берёт подходящий по настроению трек и кладёт фоном ПОД голос.

Важно: для максимального буста лучший вариант — добавить тот же трендовый звук НАТИВНО
в приложении Instagram (приглушить оригинал). Встроенный трек — база/подложка.

Приоритет фоновой дорожки в factory_reel:
  1) трек, присланный автором с этим роликом;  2) трендовый из библиотеки (тут);
  3) Jamendo (royalty-free) как запасной.
"""
from __future__ import annotations
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "library", "trending")
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus"}

# синонимы настроений в именах файлов (назови файл, напр., energetic_drive.mp3)
MOOD_WORDS = {
    "energetic": ("energetic", "energy", "drive", "драйв", "бодр", "хайп", "hype", "фонк", "phonk"),
    "calm":      ("calm", "chill", "lofi", "спокой", "лёгк", "легк", "эмбиент", "ambient"),
    "epic":      ("epic", "эпик", "cinematic", "кино", "пафос", "мощ"),
}


def lib_dir() -> str:
    os.makedirs(LIB, exist_ok=True)
    return LIB


def _tracks() -> list[str]:
    d = lib_dir()
    out = []
    for f in sorted(os.listdir(d)):
        if f.startswith("_") or f.startswith("."):
            continue
        if os.path.splitext(f)[1].lower() in AUDIO_EXT:
            out.append(os.path.join(d, f))
    return out


def have() -> bool:
    return bool(_tracks())


def pick(mood: str = "energetic") -> str | None:
    """Выбрать трендовый трек под настроение (по имени файла), иначе — самый свежий."""
    tracks = _tracks()
    if not tracks:
        return None
    mood = (mood or "").strip().lower()
    words = MOOD_WORDS.get(mood, (mood,)) if mood else ()
    for t in tracks:                        # приоритет — совпадение по настроению в имени
        name = os.path.basename(t).lower()
        if any(w and w in name for w in words):
            return t
    return max(tracks, key=os.path.getmtime)  # иначе — самый свежий добавленный


# ── рекомендация звука для РУЧНОГО добавления в Инсте (моторика алгоритма) ──
_GENRE = {
    "energetic": "энергичный фонк / хайповый хип-хоп бит / электрон с чётким дропом",
    "calm": "лёгкий lo-fi / мелодичный чилл / тёплый акустик",
    "epic": "эпичный кинематографичный бит / мощный оркестр-электрон",
}
_FMT_TWEAK = {
    "product": "ударный, с резким дропом на цифре/оффере",
    "case": "ударный, дроп на контрасте было→стало",
    "expert": "умеренный бит, не перебивает мысль",
    "story": "эмоциональный/мелодичный, нарастание к повороту",
    "leadmagnet": "бодрый, ощущение «хватай пока дают»",
    "personal": "тёплый, искренний, без агрессии",
}


def recommend(mood: str = "energetic", rtype: str = "", pace: str = "medium") -> str:
    """Текст-подсказка: какой трендовый звук из Инсты добавить ВРУЧНУЮ (нативно)."""
    genre = _GENRE.get((mood or "").lower(), _GENRE["energetic"])
    tweak = _FMT_TWEAK.get(rtype, "")
    tempo = "быстрый темп, чёткий бит" if pace == "fast" else "средний темп"
    lines = [
        "🎵 ЗВУК ДЛЯ ИНСТЫ — добавь ВРУЧНУЮ в приложении (так работает алгоритм):",
        f"• Вайб под этот ролик: {genre}" + (f"; {tweak}" if tweak else "") + f"; {tempo}.",
        "• Как найти: листай Reels → бери саунд со стрелкой ↗️ (растущий, НЕ на пике) → «Сохранить звук».",
        "• Добавь его при публикации и утяни громкость саунда до ~10-15% — голос остаётся чистым, "
        "а ролик привязывается к трендовой ленте = буст охватов.",
        "• Синхронь первый рез/хук под удар бита. Бери саунд на взлёте.",
        "⚠️ Аккаунт должен быть Creator (не Business) — иначе трендовой музыки в библиотеке не будет.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Трендовый звук: библиотека саундов")
    ap.add_argument("--mood", default="energetic")
    a = ap.parse_args()
    ts = _tracks()
    print(f"папка: {lib_dir()}")
    print(f"саундов в библиотеке: {len(ts)}")
    p = pick(a.mood)
    print(f"выбрал под '{a.mood}': {os.path.basename(p) if p else '— (пусто, кинь треки в папку)'}")
