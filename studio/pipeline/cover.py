#!/usr/bin/env python3
"""Авто-обложка/кавер под CTR: сильный кадр + крупный текст-хук + тёмный скрим.

Обложка решает клики в сетке профиля и Explore. Переиспользует Pillow (текст),
кадр из видео (ffmpeg). Опц. вырезка лица (rembg) для выноса на передний план.
"""
from __future__ import annotations
import os
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

FF = imageio_ffmpeg.get_ffmpeg_exe()
FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
RED = (232, 0, 10, 255)
WHITE = (245, 245, 250, 255)


def _font(size):
    for p in FONTS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def grab_frame(video: str, out: str, t: float = 0.6):
    subprocess.run([FF, "-y", "-ss", str(t), "-i", video, "-frames:v", "1", out],
                   check=True, capture_output=True)
    return out


def make_cover(src: str, text: str, out: str, W: int = 1080, H: int = 1920, t: float = 0.6):
    """src — видео (берём кадр) или картинка. text — хук (крупно). → PNG-обложка."""
    tmp_frame = None
    if os.path.splitext(src)[1].lower() in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
        tmp_frame = out + ".frame.jpg"
        grab_frame(src, tmp_frame, t)
        base = Image.open(tmp_frame).convert("RGB")
    else:
        base = Image.open(src).convert("RGB")
    # scale-fill в WxH
    sr, dr = base.width / base.height, W / H
    if sr > dr:
        nh = H; nw = int(H * sr)
    else:
        nw = W; nh = int(W / sr)
    base = base.resize((nw, nh)).crop(((nw - W) // 2, (nh - H) // 2, (nw - W) // 2 + W, (nh - H) // 2 + H))
    # тёмный скрим сверху и снизу для читаемости
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for y in range(H):
        a = 0
        if y < H * 0.42:
            a = int(190 * (1 - y / (H * 0.42)))
        elif y > H * 0.72:
            a = int(150 * ((y - H * 0.72) / (H * 0.28)))
        sd.line([(0, y), (W, y)], fill=(9, 9, 11, a))
    img = Image.alpha_composite(base.convert("RGBA"), scrim)
    d = ImageDraw.Draw(img)
    # крупный хук в верхней трети — перенос по ШИРИНЕ + авто-подбор кегля
    words = text.upper().split()
    maxw = W * 0.88

    def wrap(font):
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=font) <= maxw:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    fs = 116
    while fs > 46:
        font = _font(fs)
        lines = wrap(font)
        if len(lines) <= 4 and all(d.textlength(l, font=font) <= maxw for l in lines):
            break
        fs -= 6
    y = int(H * 0.10)
    for ln in lines:
        w = d.textlength(ln, font=font)
        x = (W - w) / 2
        d.text((x + 4, y + 4), ln, font=font, fill=(0, 0, 0, 190))
        d.text((x, y), ln, font=font, fill=WHITE)
        y += int(fs * 1.2)
    # красная акцент-черта
    d.rectangle([W // 2 - 60, y + 6, W // 2 + 60, y + 16], fill=RED)
    img.convert("RGB").save(out, quality=92)
    if tmp_frame and os.path.exists(tmp_frame):
        os.remove(tmp_frame)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Авто-обложка под CTR")
    ap.add_argument("src"); ap.add_argument("text"); ap.add_argument("out")
    a = ap.parse_args()
    print("обложка →", make_cover(a.src, a.text, a.out))
