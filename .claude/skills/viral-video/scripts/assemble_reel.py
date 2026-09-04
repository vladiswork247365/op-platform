#!/usr/bin/env python3
"""
Локальный движок сборки вертикального ролика из исходников (фото) — БЕЗ внешних сервисов.
Ken Burns (ffmpeg zoompan) + субтитры-PNG (Pillow overlay) + переходы xfade + CTA-карточка.

Это «нижний ярус» конвейера viral-video: работает всегда, даже когда Higgsfield выключен.
Верхний ярус (AI-анимация кадров) добавляется через коннектор Higgsfield — см. SKILL.md.

Зависимости (ставятся один раз в сессии):
    pip install imageio-ffmpeg Pillow

Запуск:
    python3 assemble_reel.py manifest.json

Формат manifest.json:
{
  "output": "reel.mp4",
  "size": [1080, 1920],
  "fps": 30,
  "xfade": 0.6,
  "brand_red": [232, 0, 10],
  "segments": [
    {"image": "/path/a.jpg", "dur": 5.0, "lines": ["СИСТЕМНЫЕ","ПРОДАЖИ"], "pos": "bottom", "transpose": true},
    ...
  ],
  "cta": {"title": "АСП", "subtitle": "Ассоциация системных продаж", "domain": "platform.systemop.top", "dur": 3.5}
}

Поля сегмента:
  image     — путь к фото
  dur       — длительность сек
  lines     — строки субтитра (1–3)
  pos       — "top" | "bottom"
  transpose — true (применить EXIF-поворот), false (пиксели уже верные, EXIF врёт),
              null/опущено (авто: применить exif_transpose)
"""
import os, sys, json, subprocess
from PIL import Image, ImageOps, ImageDraw, ImageFont
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FONT = os.environ.get("REEL_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("FFMPEG FAIL:\n" + r.stderr[-1500:] + "\n")
        raise SystemExit(1)


def prep_image(src, dst, W, H, transpose):
    im = Image.open(src).convert("RGB")
    if transpose is None or transpose:
        im = ImageOps.exif_transpose(im)
    im = ImageOps.fit(im, (W * 2, H * 2), method=Image.LANCZOS, centering=(0.5, 0.4))
    im.save(dst, quality=92)


def caption_png(lines, pos, path, W, H, red):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fs = int(H * 0.048)
    font = ImageFont.truetype(FONT, fs)
    lh = int(fs * 1.2)
    widths = [d.textbbox((0, 0), t, font=font)[2] for t in lines]
    block_w, block_h = max(widths), lh * len(lines)
    x0 = (W - block_w) // 2
    y0 = (H - block_h - int(H * 0.12)) if pos == "bottom" else int(H * 0.12)
    pad = 46
    d.rounded_rectangle([x0 - pad, y0 - pad + 8, x0 + block_w + pad, y0 + block_h + pad - 6],
                        radius=28, fill=(9, 9, 11, 165))
    bar_w = 150
    d.rounded_rectangle([(W - bar_w) // 2, y0 - pad - 26, (W + bar_w) // 2, y0 - pad - 12],
                        radius=6, fill=tuple(red) + (255,))
    for i, t in enumerate(lines):
        tx, ty = (W - widths[i]) // 2, y0 + i * lh
        d.text((tx + 3, ty + 3), t, font=font, fill=(0, 0, 0, 170))
        d.text((tx, ty), t, font=font, fill=(255, 255, 255, 255))
    img.save(path)


def fit_font(draw, text, max_w, start):
    s = start
    while s > 20:
        f = ImageFont.truetype(FONT, s)
        if draw.textbbox((0, 0), text, font=f)[2] <= max_w:
            return f
        s -= 2
    return ImageFont.truetype(FONT, 20)


def build_segment(i, seg, tmp, W, H, fps, red):
    prepped = os.path.join(tmp, f"p{i}.jpg")
    cap = os.path.join(tmp, f"cap{i}.png")
    out = os.path.join(tmp, f"seg{i}.mp4")
    dur = float(seg["dur"])
    prep_image(seg["image"], prepped, W, H, seg.get("transpose"))
    caption_png(seg["lines"], seg.get("pos", "bottom"), cap, W, H, red)
    frames = int(dur * fps)
    fc = (f"[0:v]scale={int(W*1.3)}:{int(H*1.3)},zoompan=z='min(zoom+0.0009,1.18)':d={frames}"
          f":s={W}x{H}:fps={fps}[bg];[bg][1:v]overlay=0:0,format=yuv420p[v]")
    run([FFMPEG, "-y", "-i", prepped, "-loop", "1", "-t", str(dur), "-i", cap,
         "-filter_complex", fc, "-map", "[v]", "-frames:v", str(frames), "-r", str(fps),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", out])
    return out, dur


def build_cta(cta, tmp, W, H, fps, red):
    out = os.path.join(tmp, "cta.mp4")
    dur = float(cta.get("dur", 3.5))
    img = Image.new("RGB", (W, H), (9, 9, 11))
    d = ImageDraw.Draw(img)
    f_big = ImageFont.truetype(FONT, int(H * 0.125))
    f_dom = ImageFont.truetype(FONT, int(H * 0.031))
    f_mid = fit_font(d, cta["subtitle"], W - 140, int(H * 0.029))

    def ctext(y, text, font, fill):
        w = d.textbbox((0, 0), text, font=font)[2]
        d.text(((W - w) // 2, y), text, font=font, fill=fill)

    ctext(int(H * 0.31), cta["title"], f_big, tuple(red))
    ctext(int(H * 0.47), cta["subtitle"], f_mid, (240, 240, 245))
    d.rounded_rectangle([(W - 320) // 2, int(H * 0.53), (W + 320) // 2, int(H * 0.535)], radius=5, fill=tuple(red))
    ctext(int(H * 0.557), cta["domain"], f_dom, (255, 255, 255))
    still = os.path.join(tmp, "cta.png")
    img.save(still)
    frames = int(dur * fps)
    fc = f"[0:v]zoompan=z='min(zoom+0.0004,1.06)':d={frames}:s={W}x{H}:fps={fps},format=yuv420p[v]"
    run([FFMPEG, "-y", "-i", still, "-filter_complex", fc, "-map", "[v]", "-frames:v", str(frames),
         "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", out])
    return out, dur


def concat_xfade(clips, output, W, H, xfade):
    inputs = []
    for c, _ in clips:
        inputs += ["-i", c]
    filt, prev, offset = [], "0:v", 0.0
    durs = [d for _, d in clips]
    for i in range(1, len(clips)):
        offset += durs[i - 1] - xfade
        lbl = f"x{i}"
        filt.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={xfade}:offset={offset:.3f}[{lbl}]")
        prev = lbl
    run([FFMPEG, "-y", *inputs, "-filter_complex", ";".join(filt), "-map", f"[{prev}]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", output])
    return output


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    m = json.load(open(sys.argv[1], encoding="utf-8"))
    W, H = m.get("size", [1080, 1920])
    fps = m.get("fps", 30)
    xfade = m.get("xfade", 0.6)
    red = m.get("brand_red", [232, 0, 10])
    output = m.get("output", "reel.mp4")
    tmp = os.path.join(os.path.dirname(os.path.abspath(output)) or ".", "_reel_tmp")
    os.makedirs(tmp, exist_ok=True)

    clips = []
    for i, seg in enumerate(m["segments"]):
        print("сегмент", i, os.path.basename(seg["image"]))
        clips.append(build_segment(i, seg, tmp, W, H, fps, red))
    if m.get("cta"):
        print("CTA")
        clips.append(build_cta(m["cta"], tmp, W, H, fps, red))
    print("склейка...")
    concat_xfade(clips, output, W, H, xfade)
    print("ГОТОВО:", output)


if __name__ == "__main__":
    main()
