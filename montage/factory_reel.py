#!/usr/bin/env python3
"""Оркестратор контент-завода: сценарий → готовый ролик из 3 частей.

Связывает:
  сценарий (scriptwriter) → озвучка клон-голосом (ElevenLabs) → твои кадры авто →
  субтитры по таймингам голоса → плашки-акценты → фоновая музыка → ролик,
  который режется на 3 части для просмотра/правок, финал = целый ролик.

Всё мягко деградирует: нет ElevenLabs — build() вернёт None; нет ключа музыки —
соберётся без музыки.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time

import imageio_ffmpeg

import voiceover
try:
    import eleven
except Exception:
    eleven = None
try:
    import music
except Exception:
    music = None

FF = imageio_ffmpeg.get_ffmpeg_exe()
HERE = os.path.dirname(os.path.abspath(__file__))


def _inject_cards(edl: dict, script: dict):
    """Разложить плашки сценария по битам: хук — первой, остальные равномерно."""
    beats = edl.get("beats") or []
    if not beats:
        return
    hook = (script.get("hook") or "").strip()
    if hook:
        beats[0]["card"] = {"headline": hook, "label": "", "sub": "", "color": "red", "yf": 0.13}
    cards = script.get("cards") or []
    n = len(beats)
    for i, c in enumerate(cards):
        bi = min(n - 1, int((i + 1) / (len(cards) + 1) * n))
        if beats[bi].get("card"):
            bi = min(n - 1, bi + 1)
        beats[bi]["card"] = {"label": c.get("label", ""), "headline": c.get("headline", ""),
                             "sub": c.get("sub", ""), "color": c.get("color", "yellow"), "yf": 0.13}


def _mix_bg(video: str, music_file: str, out: str, gain_db: int = -18) -> str:
    """Подмешать фоновую музыку под голос (музыка тише, чуть глуше на пиках голоса)."""
    dur = voiceover.media_dur(video)
    fade = max(0.0, dur - 1.2)
    try:
        subprocess.run([FF, "-y", "-i", video, "-i", music_file, "-filter_complex",
                        f"[1:a]volume={gain_db}dB,afade=out:st={fade:.2f}:d=1.2[m];"
                        f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,dynaudnorm[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "160k", "-movflags", "+faststart", out], check=True,
                       capture_output=True)
        return out
    except Exception:
        return video   # не вышло — оставляем без музыки


def build(footage_dir: str, script: dict, out_dir: str, voice_id: str | None = None,
          gray: bool = False, mood: str = "energetic", fps: int = 30, status_cb=None):
    """Собрать полный ролик по сценарию. → путь к ролику или None (нет озвучки)."""
    def _st(t):
        if status_cb:
            try:
                status_cb(t)
            except Exception:
                pass
    if not (eleven and eleven.have_key()):
        return None
    text = " ".join(s for s in (script.get("part1"), script.get("part2"),
                                script.get("part3")) if s).strip()
    if not text:
        return None
    _st("🎙 Озвучиваю сценарий твоим голосом…")
    audio = os.path.join(footage_dir, "_voice.mp3")
    res = eleven.tts_timed(text, audio, voice_id)
    if not res:
        return None
    _, words = res
    total = voiceover.media_dur(audio)
    if total <= 0:
        return None
    _st("🎬 Собираю видеоряд под озвучку…")
    edl = voiceover.build_edl(footage_dir, audio, words, total, fps=fps, sub_y=0.8)
    if gray:
        edl["output"]["grayscale"] = True
    _inject_cards(edl, script)
    plan = os.path.join(footage_dir, "_factory.edl.json")
    with open(plan, "w", encoding="utf-8") as f:
        json.dump(edl, f, ensure_ascii=False, indent=2)
    os.makedirs(out_dir, exist_ok=True)
    reel = os.path.join(out_dir, f"reel_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    _st("🎨 Рендерю (озвучка + субтитры + плашки)…")
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    "--edl", plan, "--src", footage_dir, "--out", reel], check=True)
    # фоновая музыка: 1) трек, который прислал автор; иначе 2) Jamendo по настроению
    mf = _user_music(footage_dir)
    if not mf and music and music.have_key():
        _st("🎵 Подбираю музыку…")
        mf = music.get_track(os.path.join(footage_dir, "_bg.mp3"), mood)
    if mf:
        _st("🎵 Накладываю музыку под голос…")
        mixed = os.path.join(out_dir, "_mixed.mp4")
        if _mix_bg(reel, mf, mixed) == mixed:
            try:
                os.replace(mixed, reel)
            except Exception:
                pass
    return reel


_AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}


def _user_music(footage_dir: str):
    """Трек, который прислал автор (аудио-файл среди исходников). None — если нет."""
    try:
        for f in sorted(os.listdir(footage_dir)):
            if f.startswith("_"):
                continue
            if os.path.splitext(f)[1].lower() in _AUDIO_EXT:
                return os.path.join(footage_dir, f)
    except Exception:
        pass
    return None


def split_three(reel: str, out_dir: str):
    """Порезать готовый ролик на 3 равные части (для просмотра/правок). → [p1,p2,p3]."""
    total = voiceover.media_dur(reel)
    if total <= 0:
        return []
    seg = total / 3.0
    parts = []
    for i in range(3):
        p = os.path.join(out_dir, f"part{i+1}.mp4")
        ss = round(i * seg, 2)
        t = round(seg if i < 2 else total - ss, 2)
        try:
            subprocess.run([FF, "-y", "-ss", f"{ss}", "-i", reel, "-t", f"{t}",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                            "-movflags", "+faststart", p], check=True, capture_output=True)
            parts.append(p)
        except Exception:
            pass
    return parts
