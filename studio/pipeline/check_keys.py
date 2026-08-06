#!/usr/bin/env python3
"""Проверка наличия API-ключей студии. Значения ключей в вывод/чат НЕ попадают —
только факт наличия. Ключи держать в studio/.env (chmod 600)."""
import os

KEYS = {
    "ELEVEN_KEY":         "ElevenLabs — Scribe (транскрипт со словами), TTS/клон-голос, музыка",
    "KIE_KEY":            "kie.ai — видеогенерация (Kling 3.0 / Seedance 2 / Veo 3.1 / Wan 2.5 / Grok)",
    "OPENROUTER_API_KEY": "OpenRouter — fallback тех же видеомоделей",
    "XAI_API_KEY":        "xAI — Grok Imagine (дешёвое оживление фото, image-to-video)",
    "PEXELS_API_KEY":     "Pexels — бесплатный сток b-roll",
}


def load_env(path=None):
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    load_env()
    print("Ключи студии (значения скрыты):")
    have = 0
    for k, why in KEYS.items():
        ok = bool(os.environ.get(k))
        have += ok
        print(f"  [{'✓' if ok else '—'}] {k:20} {why}")
    print(f"\nЗадано {have}/{len(KEYS)}. Пустые — вписать в studio/.env (chmod 600).")


if __name__ == "__main__":
    main()
