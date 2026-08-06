#!/usr/bin/env python3
"""Генерирует синтетические исходники в montage/sources/ для самопроверки движка:
2 «видео» (цвет + тон + движущийся бокс), 2 фото (jpg + heic), музыкальный тон.
Реальные клипы потом просто кладутся в sources/ с нужными именами."""
import os, subprocess, imageio_ffmpeg
from PIL import Image, ImageDraw
import pillow_heif; pillow_heif.register_heif_opener()

FF = imageio_ffmpeg.get_ffmpeg_exe()
SRC = os.path.join(os.path.dirname(__file__), "sources")
os.makedirs(SRC, exist_ok=True)

def vid(name, color, hz, secs=10):
    out = os.path.join(SRC, name)
    subprocess.run([FF, "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s=1280x720:d={secs}:r=30",
        "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={secs}",
        "-vf", "drawbox=x=t*120:y=200:w=180:h=180:color=white@0.9:t=fill",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out],
        check=True, capture_output=True)
    print("  video", name)

def photo(name, color, heic=False):
    img = Image.new("RGB", (1200, 1600), color)
    d = ImageDraw.Draw(img); d.ellipse([300, 500, 900, 1100], fill="white")
    out = os.path.join(SRC, name)
    img.save(out, "HEIF" if heic else None)
    print("  photo", name)

def music(name="music.m4a", secs=40):
    out = os.path.join(SRC, name)
    subprocess.run([FF, "-y", "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={secs}", "-c:a", "aac", out],
        check=True, capture_output=True)
    print("  music", name)

if __name__ == "__main__":
    vid("clipA.mp4", "navy", 180)
    vid("clipB.mp4", "darkgreen", 240)
    photo("photo1.jpg", (200, 60, 60))
    photo("photo2.heic", (60, 60, 200), heic=True)
    music()
    print("готово →", SRC)
