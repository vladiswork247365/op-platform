#!/usr/bin/env python3
"""Детекция битов музыки (librosa) → тайминги долей для нарезки «в ритм».

Виральная техника: склейки на бит держат внимание. auto_edl может подтягивать
границы кусков к ближайшему биту. Мягкий откат: нет librosa/аудио → пусто.
"""
from __future__ import annotations
import sys


def beat_times(audio_path):
    """→ (список времён битов в секундах, темп BPM). Пусто при недоступности.
    Аудио декодируем в wav через ffmpeg — так librosa читает любой формат."""
    import os
    import subprocess
    import tempfile
    wav = None
    try:
        import imageio_ffmpeg
        import librosa
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        wav = tempfile.mktemp(suffix=".wav")
        subprocess.run([ff, "-y", "-i", audio_path, "-ac", "1", "-ar", "22050", wav],
                       capture_output=True)
        y, sr = librosa.load(wav, sr=22050, mono=True)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        t = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
        return [round(float(b), 3) for b in beats], round(t, 1)
    except Exception as e:
        sys.stderr.write(f"[beat_sync] недоступно ({type(e).__name__}: {str(e)[:80]})\n")
        return [], 0.0
    finally:
        if wav and os.path.exists(wav):
            os.remove(wav)


def snap(t, beats, tol=0.25):
    """Подтянуть время t к ближайшему биту, если он ближе tol секунд."""
    if not beats:
        return t
    nearest = min(beats, key=lambda b: abs(b - t))
    return nearest if abs(nearest - t) <= tol else t


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Биты музыки (librosa)")
    ap.add_argument("audio")
    a = ap.parse_args()
    beats, bpm = beat_times(a.audio)
    print(f"BPM≈{bpm}, битов: {len(beats)}; первые: {beats[:8]}")
