#!/usr/bin/env python3
"""Режим «говорю, но звука нет».

Ты снимаешь ролик молча / без чистого звука и даёшь СКРИПТ (текст). Система:
  1) озвучивает скрипт твоим клон-голосом (ElevenLabs) + берёт тайминги слов;
  2) собирает видеоряд из твоих исходников БЕЗ их родного звука под длину озвучки;
  3) кладёт озвучку как основную дорожку, а субтитры — синхронно по словам (бренд-стиль).

Нужен ELEVEN_KEY + голос (ELEVEN_VOICE_ID или клон). Без ключа build() вернёт None,
и бот честно скажет, что нужно подключить голос.
"""
from __future__ import annotations
import glob
import json
import os
import re
import subprocess
import sys
import time

import imageio_ffmpeg

import auto_edl
import eleven

FF = imageio_ffmpeg.get_ffmpeg_exe()
HERE = os.path.dirname(os.path.abspath(__file__))

MOTIONS = ["punch", "zoomin", "kick", "zoomout"]
TRANS = ["slideleft", None, "slideup", None, "smoothright", None, "wipeleft", None]
BEAT = 3.0


def media_dur(path: str) -> float:
    p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _words_to_cues(words, t0: float, t1: float, per: int = 3, sub_y: float = 0.835):
    """Слова озвучки в окне [t0,t1] → пословные субтитры beat'а (активное слово в плашке)."""
    seg = [w for w in words if t0 - 0.05 <= w["start"] < t1]
    cues = []
    for i in range(0, len(seg), per):
        ch = seg[i:i + per]
        cues.append({
            "t0": round(max(0.0, ch[0]["start"] - t0), 2),
            "t1": round(min(t1, ch[-1]["end"]) - t0, 2),
            "lines": [" ".join(w["word"] for w in ch)],
            "highlight": ch[-1]["word"].strip(auto_edl.STRIP),
            "pos": "lower", "yf": sub_y,
        })
    return cues


def build_edl(footage_dir: str, audio_file: str, words: list, total: float,
              fps: int = 30, sub_y: float = 0.835, pace: str = "medium") -> dict:
    """EDL: видеоряд под длину озвучки, родной звук выключен, субтитры по словам озвучки.

    pace='fast' — плотнее резы и субтитры (драйв); 'medium' — обычный ритм.
    """
    files = sorted(glob.glob(os.path.join(footage_dir, "*")))
    vids = [f for f in files if os.path.splitext(f)[1].lower() in auto_edl.VIDEO_EXT]
    imgs = [f for f in files if os.path.splitext(f)[1].lower() in auto_edl.IMAGE_EXT]
    srcs = vids or imgs
    if not srcs:
        raise SystemExit("нет видео/фото для видеоряда")

    beat_len = 1.7 if pace == "fast" else BEAT      # плотность резов
    per = 2 if pace == "fast" else 3                # плотность субтитров
    beats, acc, i = [], 0.0, 0
    cursor = {f: 0.0 for f in vids}          # позиция чтения внутри каждого клипа
    total = max(total, 1.0)
    while acc < total - 0.05:
        src = srcs[i % len(srcs)]
        remain = total - acc
        if src in vids:
            d = media_dur(src) or beat_len
            seg = min(beat_len, remain, max(1.0, d))
            pos = cursor[src]
            if pos + seg > d:                # клип кончился — с начала
                pos = 0.0
            cursor[src] = pos + seg
            beat = {"src": os.path.basename(src), "in": round(pos, 2),
                    "out": round(pos + seg, 2), "speed": 1.0,
                    "motion": MOTIONS[i % len(MOTIONS)], "audio": "mute"}
        else:
            seg = min(2.5, remain)
            beat = {"src": os.path.basename(src), "dur": round(seg, 2),
                    "motion": "kenburns_in" if i % 2 == 0 else "kenburns_out", "audio": "mute"}
        if i == 0:                            # панч-вход
            beat["motion"], beat["punch"] = "punch", 1.08
        else:
            tr = TRANS[i % len(TRANS)]
            if tr:
                beat["transition"] = tr
        cues = _words_to_cues(words, acc, acc + seg, per=per, sub_y=sub_y)
        if cues:
            beat["captions"] = cues
        beats.append(beat)
        acc += seg
        i += 1
        if i > 400:                           # предохранитель
            break

    edl = {"output": {"w": 1080, "h": 1920, "fps": fps}, "beats": beats,
           "music": {"file": os.path.basename(audio_file), "gain_db": 0}}  # озвучка = основная дорожка
    return edl


def build(footage_dir: str, text: str, out_dir: str, voice_id: str | None = None,
          fps: int = 30, sub_y: float = 0.835, grayscale: bool = False,
          status_cb=None):
    """Полный проход режима озвучки. → (outfile, words) или None (нет ключа/голоса/ошибка)."""
    def _st(t):
        if status_cb:
            try:
                status_cb(t)
            except Exception:
                pass
    if not eleven.have_key():
        return None
    _st("🎙 Озвучиваю скрипт твоим голосом (ElevenLabs)…")
    audio_file = os.path.join(footage_dir, "_voice.mp3")
    res = eleven.tts_timed(text, audio_file, voice_id)
    if not res:
        return None
    _, words = res
    total = media_dur(audio_file)
    if total <= 0:
        return None
    _st("🎬 Собираю видеоряд под озвучку…")
    edl = build_edl(footage_dir, audio_file, words, total, fps=fps, sub_y=sub_y)
    if grayscale:
        edl["output"]["grayscale"] = True
    plan = os.path.join(footage_dir, "_voiceover.edl.json")
    with open(plan, "w", encoding="utf-8") as f:
        json.dump(edl, f, ensure_ascii=False, indent=2)
    os.makedirs(out_dir, exist_ok=True)
    outfile = os.path.join(out_dir, f"reel_vo_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    _st("🎨 Рендерю ролик (озвучка + субтитры)…")
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    "--edl", plan, "--src", footage_dir, "--out", outfile], check=True)
    return outfile, words


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Режим «говорю без звука»: скрипт → озвучка → ролик")
    ap.add_argument("--src", required=True, help="папка с исходниками (видео/фото)")
    ap.add_argument("--text", required=True, help="скрипт для озвучки")
    ap.add_argument("--out", default="out")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--gray", action="store_true")
    a = ap.parse_args()
    r = build(a.src, a.text, a.out, a.voice, grayscale=a.gray,
              status_cb=lambda t: print(t))
    print("не удалось (нет ELEVEN_KEY/voice_id?)" if not r else f"✅ {r[0]}")
