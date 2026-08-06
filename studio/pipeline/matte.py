#!/usr/bin/env python3
"""Вырезка фона (rembg) + split-screen — «наслоение кадров» и retention-низ.

- cutout_image: вырезать спикера/объект (для наложения на b-roll).
- split_screen: верх — talking-head, низ — «satisfying» b-roll/gameplay (приём удержания TikTok/Shorts).
Мягкий откат: если rembg недоступен — cutout возвращает исходник.
"""
from __future__ import annotations
import subprocess

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()


def cutout_image(inp: str, out: str, model: str = "u2netp"):
    try:
        from rembg import remove, new_session
        from PIL import Image
        img = Image.open(inp).convert("RGBA")
        remove(img, session=new_session(model)).save(out)
        return out
    except Exception as e:
        import shutil, sys
        sys.stderr.write(f"[matte] rembg недоступен ({str(e)[:80]}) — без вырезки\n")
        shutil.copy(inp, out)
        return out


def split_screen(top: str, bottom: str, out: str, W: int = 1080, H: int = 1920):
    """Верх — talking-head, низ — b-roll/gameplay. Вертикаль 9:16, звук сверху."""
    h2 = H // 2
    vf = (f"[0:v]scale={W}:{h2}:force_original_aspect_ratio=increase,crop={W}:{h2},setsar=1[t];"
          f"[1:v]scale={W}:{h2}:force_original_aspect_ratio=increase,crop={W}:{h2},setsar=1[b];"
          f"[t][b]vstack=inputs=2[v]")
    subprocess.run([FF, "-y", "-i", top, "-i", bottom, "-filter_complex", vf,
                    "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    "-movflags", "+faststart", out], check=True, capture_output=True)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Вырезка фона / split-screen")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("cutout"); c.add_argument("inp"); c.add_argument("out")
    s = sub.add_parser("split"); s.add_argument("top"); s.add_argument("bottom"); s.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "cutout":
        print("cutout →", cutout_image(a.inp, a.out))
    elif a.cmd == "split":
        print("split →", split_screen(a.top, a.bottom, a.out))
