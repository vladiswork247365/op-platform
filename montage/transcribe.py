#!/usr/bin/env python3
"""Транскрибация речи (faster-whisper) → слова с таймингами для авто-субтитров.

Опционально и устойчиво: если faster-whisper или модель недоступны (нет сети/
пакета) — возвращает None, и пайплайн откатывается на хук из имени файла.
Результат кешируется рядом с исходником (<файл>.words.json), чтобы не гонять
распознавание повторно.
"""
from __future__ import annotations
import json
import os
import sys

_MODEL = None
_CACHE: dict[str, list | None] = {}


def _load(model_size: str = "small"):
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _MODEL


def transcribe_words(path: str, model_size: str = "small", lang: str = "ru"):
    """→ [{'start','end','word'}, ...] или None при недоступности распознавания."""
    if path in _CACHE:
        return _CACHE[path]
    side = path + ".words.json"
    if os.path.exists(side):
        try:
            with open(side, encoding="utf-8") as f:
                _CACHE[path] = json.load(f)
                return _CACHE[path]
        except Exception:
            pass
    try:
        model = _load(model_size)
        segments, _ = model.transcribe(path, language=lang, word_timestamps=True, vad_filter=True)
        words = []
        for seg in segments:
            for w in (seg.words or []):
                words.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()})
        _CACHE[path] = words
        try:
            with open(side, "w", encoding="utf-8") as f:
                json.dump(words, f, ensure_ascii=False)
        except Exception:
            pass
        return words
    except Exception as e:
        sys.stderr.write(f"[transcribe] недоступно ({type(e).__name__}: {str(e)[:80]}) "
                         f"— субтитры возьму из имени файла\n")
        _CACHE[path] = None
        return None


def words_in_range(words, t0: float, t1: float):
    if not words:
        return []
    return [w["word"] for w in words if t0 - 0.15 <= w["start"] < t1]


def chunk_lines(word_list, per: int = 3, maxlines: int = 2):
    lines = [" ".join(word_list[i:i + per]) for i in range(0, len(word_list), per)]
    return lines[:maxlines]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Транскрибация файла в слова с таймингами")
    ap.add_argument("path")
    ap.add_argument("--lang", default="ru")
    a = ap.parse_args()
    w = transcribe_words(a.path, lang=a.lang)
    print("недоступно" if w is None else json.dumps(w[:20], ensure_ascii=False, indent=2))
