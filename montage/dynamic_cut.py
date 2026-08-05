#!/usr/bin/env python3
"""Динамическая обрезка исходника через auto-editor (8K⭐): вырезает паузы и
тишину, делает джамп-каты, подтягивает темп — «динамика, обрезка, быстрота».

Мягкий откат: если auto-editor недоступен — возвращает исходник как есть.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys

import imageio_ffmpeg


def _ffmpeg_on_path():
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    d = os.path.dirname(ff)
    link = os.path.join(d, "ffmpeg")
    if not os.path.exists(link):
        try:
            os.symlink(ff, link)
        except OSError:
            pass
    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def tighten(src: str, out: str, threshold: str = "4%", margin: float = 0.2):
    """Поджать клип (убрать мёртвый воздух). → (path, changed:bool)."""
    if shutil.which("auto-editor") is None:
        shutil.copy(src, out)
        return out, False
    _ffmpeg_on_path()
    cmd = ["auto-editor", src, "--no-open", "--margin", f"{margin}s",
           "--edit", f"audio:threshold={threshold}", "-o", out]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if p.returncode == 0 and os.path.exists(out):
            return out, True
        sys.stderr.write(f"[dynamic_cut] auto-editor не сработал — беру исходник\n{p.stderr[-300:]}\n")
    except Exception as e:
        sys.stderr.write(f"[dynamic_cut] {type(e).__name__}: {str(e)[:120]} — беру исходник\n")
    shutil.copy(src, out)
    return out, False


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Поджать клип (auto-editor)")
    ap.add_argument("src")
    ap.add_argument("out")
    a = ap.parse_args()
    _, changed = tighten(a.src, a.out)
    print("поджато" if changed else "без изменений", "→", a.out)
