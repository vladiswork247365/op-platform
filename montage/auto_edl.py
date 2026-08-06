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

try:
    from transcribe import transcribe_words, words_in_range, chunk_lines
except Exception:  # модуль/зависимости могут отсутствовать — работаем без субтитров
    transcribe_words = None
try:
    import beat_sync  # нарезка в бит музыки (librosa)
except Exception:
    beat_sync = None
try:
    import stock       # b-roll со стока в тему (Pexels)
except Exception:
    stock = None

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


STRIP = ".,!?—:;«»\"'()"


def word_cues(words, t0: float, t1: float, speed: float, per: int = 3):
    """Пословные субтитры (стиль SubMagic): слова сегмента [t0,t1] → cue-и с
    таймингами относительно beat'а (с учётом ускорения), активное слово красным."""
    seg = [w for w in words if t0 - 0.15 <= w["start"] < t1]
    cues = []
    for i in range(0, len(seg), per):
        chunk = seg[i:i + per]
        cues.append({
            "t0": round(max(0.0, (chunk[0]["start"] - t0) / speed), 2),
            "t1": round((chunk[-1]["end"] - t0) / speed, 2),
            "lines": [" ".join(w["word"] for w in chunk)],
            "highlight": chunk[-1]["word"].strip(STRIP),
            "pos": "lower",
        })
    return cues


def build_edl(srcdir: str, target: float = 34.0, fps: int = 30, subs: bool = True) -> dict:
    files = sorted(glob.glob(os.path.join(srcdir, "*")))
    vids = [f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXT]
    imgs = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXT]
    music = [f for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT]
    if not vids and not imgs:
        raise SystemExit(f"нет видео/фото в {srcdir}")

    vids.sort(key=duration, reverse=True)        # главный клип = самый длинный
    beats, used, count, photo_i, hook_done = [], 0.0, 0, 0, False
    BEAT = 3.0

    # биты музыки → нарезка «в ритм» (склейки на бит держат внимание)
    beat_grid = []
    if music and beat_sync:
        beat_grid, _bpm = beat_sync.beat_times(music[0])
    all_words = []

    MOTIONS = ["punch", "zoomin", "none", "zoomout"]
    for v in vids:
        words = transcribe_words(v) if (subs and transcribe_words) else None
        if words:
            all_words.extend(words)
        d, pos = duration(v), 0.0
        while pos + 1.0 < d and used < target:
            end = min(pos + BEAT, d)
            if beat_grid:  # подтянуть рез к ближайшему биту
                s = beat_sync.snap(pos + BEAT, beat_grid, tol=0.7)
                if pos + 1.0 <= s <= d:
                    end = s
            seg = round(end - pos, 3)
            beat = {"src": os.path.basename(v), "in": round(pos, 2), "out": round(pos + seg, 2),
                    "speed": 1.05, "motion": MOTIONS[count % len(MOTIONS)]}
            # жёсткие резы = динамика (переходы xfade доступны опционально в EDL)
            spoken = words_in_range(words, pos, pos + seg) if words else []
            if not hook_done:
                if spoken:
                    beat["text"] = {"lines": chunk_lines(spoken, per=2), "pos": "center",
                                    "size": 88, "highlight": spoken[-1].strip(STRIP)}
                else:
                    beat["text"] = {"lines": wrap_words(clean_title(v)), "pos": "center", "size": 92}
                beat["motion"], beat["punch"] = "punch", 1.08
                beat.pop("transition", None)
                hook_done = True
            elif words:
                cues = word_cues(words, pos, pos + seg, beat["speed"])
                if cues:
                    beat["captions"] = cues
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

    # b-roll со стока в тему (Pexels) по ключевым словам речи — «наслоение кадров»
    if stock and getattr(stock, "PEXELS_KEY", None) and all_words:
        for n, kw in enumerate(stock.keywords(all_words, top=2)):
            path = os.path.join(srcdir, f"_stock_{n}.mp4")
            if stock.fetch_stock(kw, path):
                insert = {"src": os.path.basename(path), "in": 0.0, "out": 2.0,
                          "speed": 1.0, "motion": "zoomin", "audio": "mute",
                          "text": {"lines": [kw.upper()], "pos": "lower", "highlight": kw}}
                beats.insert(min(len(beats) // 2 + 1 + n, len(beats)), insert)

    edl = {"output": {"w": 1080, "h": 1920, "fps": fps}, "beats": beats}
    if music:
        edl["music"] = {"file": os.path.basename(music[0]), "gain_db": -18}
    return edl


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Автогенерация EDL из папки исходников")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default="-")
    ap.add_argument("--target", type=float, default=34.0)
    ap.add_argument("--no-subs", action="store_true", help="без транскрибации, хук из имени файла")
    a = ap.parse_args()
    edl = build_edl(a.src, a.target, subs=not a.no_subs)
    s = json.dumps(edl, ensure_ascii=False, indent=2)
    if a.out == "-":
        print(s)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(s)
        print(f"saved {a.out} | {len(edl['beats'])} beats, музыка: {'да' if 'music' in edl else 'нет'}")
