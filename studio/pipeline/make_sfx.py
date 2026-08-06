#!/usr/bin/env python3
"""Синтез CC0-пака звуковых эффектов через ffmpeg (без скачиваний).

Генерит whoosh / pop / ding / riser в studio/sfx/. Используется движком для
авто-вставки SFX на монтажных склейках и появлении текста (приём удержания:
звук перезапускает внимание на каждом резе). Нормализация — фикс-гейн (ebur128
врёт на окнах < 0.4 с, поэтому короткие звуки не гоним через loudnorm).
"""
import os
import subprocess
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sfx")
os.makedirs(OUT, exist_ok=True)


def _run(args, name):
    p = subprocess.run([FF, "-y", *args, os.path.join(OUT, name)], capture_output=True, text=True)
    if p.returncode != 0:
        print("FAIL", name, p.stderr[-300:])
    else:
        print("  •", name)


def build():
    # whoosh — розовый шум с полосой и быстрым fade (склейки)
    _run(["-f", "lavfi", "-i", "anoisesrc=d=0.35:c=pink:a=0.7",
          "-af", "highpass=f=250,lowpass=f=6500,afade=t=in:d=0.04,afade=t=out:st=0.14:d=0.21,volume=0.5",
          "-ac", "2", "-ar", "44100"], "whoosh.wav")
    # pop — короткий тон-щелчок (появление текста)
    _run(["-f", "lavfi", "-i", "sine=frequency=880:duration=0.09",
          "-af", "afade=t=out:st=0.02:d=0.07,volume=0.6", "-ac", "2", "-ar", "44100"], "pop.wav")
    # ding — затухающий тон (акцент/highlight-слово)
    _run(["-f", "lavfi", "-i", "sine=frequency=1320:duration=0.5",
          "-af", "afade=t=out:st=0.05:d=0.45,volume=0.4", "-ac", "2", "-ar", "44100"], "ding.wav")
    # riser — нарастающий свип (перед хуком/акцентом)
    _run(["-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*(220+900*t/0.8)*t)':d=0.8",
          "-af", "afade=t=in:d=0.6,afade=t=out:st=0.7:d=0.1", "-ac", "2", "-ar", "44100"], "riser.wav")


if __name__ == "__main__":
    build()
    print("SFX-пак готов →", OUT)
