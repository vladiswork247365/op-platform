#!/usr/bin/env python3
"""Автогенерация EDL-плана из папки исходников — черновой ДИНАМИЧНЫЙ монтаж
без ручного плана: нарезка длинных клипов на биты, рефрейминг 9:16, зум-панчи,
Ken Burns на фото, музыка. Хук берётся из имени файла.

Умный подбор субтитров/хука ПО СМЫСЛУ речи требует транскрибации (отдельный
модуль) — здесь делается динамика картинки, а точные тексты правятся сверху.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import re
import subprocess

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav"}


def duration(path: str) -> float:
    p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def clean_title(fn: str) -> str:
    base = os.path.splitext(os.path.basename(fn))[0]
    base = re.sub(r"\.(mp4|mov|m4v)$", "", base, flags=re.I)
    base = re.sub(r"\(.*?\)", "", base)          # убрать (online-video-cutter.com)
    base = re.sub(r"[_\-]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base.upper()


def wrap_words(text: str, per: int = 2, maxlines: int = 2):
    w = text.split()
    lines = [" ".join(w[i:i + per]) for i in range(0, len(w), per)]
    return lines[:maxlines] or [text]


def build_edl(srcdir: str, target: float = 34.0, fps: int = 30) -> dict:
    files = sorted(glob.glob(os.path.join(srcdir, "*")))
    vids = [f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXT]
    imgs = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXT]
    music = [f for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT]
    if not vids and not imgs:
        raise SystemExit(f"нет видео/фото в {srcdir}")

    vids.sort(key=duration, reverse=True)        # главный клип = самый длинный
    beats, used, count, photo_i, hook_done = [], 0.0, 0, 0, False
    BEAT = 3.0

    for v in vids:
        d, pos = duration(v), 0.0
        while pos + 1.0 < d and used < target:
            seg = min(BEAT, d - pos)
            beat = {"src": os.path.basename(v), "in": round(pos, 2), "out": round(pos + seg, 2),
                    "speed": 1.05, "motion": "punch" if count % 2 == 0 else "none"}
            if not hook_done:
                beat["text"] = {"lines": wrap_words(clean_title(v)), "pos": "center", "size": 92}
                beat["motion"], beat["punch"], hook_done = "punch", 1.08, True
            beats.append(beat)
            used += seg / 1.05
            pos += seg
            count += 1
            if count % 3 == 0 and photo_i < len(imgs) and used < target:
                beats.append({"src": os.path.basename(imgs[photo_i]), "dur": 0.5,
                              "motion": "kenburns_in" if photo_i % 2 == 0 else "kenburns_out"})
                photo_i += 1
                used += 0.5
            if used >= target:
                break
        if used >= target:
            break

    edl = {"output": {"w": 1080, "h": 1920, "fps": fps}, "beats": beats}
    if music:
        edl["music"] = {"file": os.path.basename(music[0]), "gain_db": -18}
    return edl


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Автогенерация EDL из папки исходников")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default="-")
    ap.add_argument("--target", type=float, default=34.0)
    a = ap.parse_args()
    edl = build_edl(a.src, a.target)
    s = json.dumps(edl, ensure_ascii=False, indent=2)
    if a.out == "-":
        print(s)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(s)
        print(f"saved {a.out} | {len(edl['beats'])} beats, музыка: {'да' if 'music' in edl else 'нет'}")
