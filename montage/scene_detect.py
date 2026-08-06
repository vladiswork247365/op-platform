#!/usr/bin/env python3
"""Детекция смены сцен (PySceneDetect) → точки реза по реальным визуальным границам,
чтобы куски не начинались/кончались в середине действия. Мягкий откат: пусто."""
from __future__ import annotations
import sys


def scene_boundaries(path: str, threshold: float = 27.0):
    """→ список времён (сек) границ сцен внутри клипа. Пусто при недоступности."""
    try:
        from scenedetect import detect, ContentDetector
        scenes = detect(path, ContentDetector(threshold=threshold))
        # границы = концы сцен (кроме самого конца ролика)
        bounds = sorted({round(s[1].get_seconds(), 3) for s in scenes})
        return [b for b in bounds if b > 0.3]
    except Exception as e:
        sys.stderr.write(f"[scene_detect] недоступно ({type(e).__name__}: {str(e)[:80]})\n")
        return []


def snap(t: float, bounds, tol: float = 1.0):
    """Подтянуть точку реза к ближайшей границе сцены, если она ближе tol секунд."""
    if not bounds:
        return t
    nearest = min(bounds, key=lambda b: abs(b - t))
    return nearest if abs(nearest - t) <= tol else t


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Границы сцен (PySceneDetect)")
    ap.add_argument("path")
    ap.add_argument("--threshold", type=float, default=27.0)
    a = ap.parse_args()
    b = scene_boundaries(a.path, a.threshold)
    print(f"сцен-границ: {len(b)}; первые: {b[:10]}")
