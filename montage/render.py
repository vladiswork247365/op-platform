#!/usr/bin/env python3
"""Движок монтажа Reels-фабрики.

Читает EDL-план (JSON) + исходники → рендерит вертикальный (9:16) динамичный
ролик: нарезка, рефрейминг в 1080x1920, зум-панч на видео, Ken Burns на фото,
субтитры/хуки (Pillow overlay), опциональная музыкальная подложка.

Запуск:
    python3 montage/render.py --edl montage/examples/sosiski.edl.json \
        --src montage/sources --out montage/out/reel.mp4

EDL-формат — см. montage/README.md. Каждый beat = один кусок таймлайна.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile

import imageio_ffmpeg

from captions import render_caption, find_font

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
IMG_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        sys.stderr.write("\n[ffmpeg FAIL] " + " ".join(map(str, cmd)) + "\n")
        sys.stderr.write(p.stderr[-2500:] + "\n")
        raise SystemExit(1)
    return p


def has_audio(path: str) -> bool:
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True)
    return "Audio:" in p.stderr


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMG_EXT


def heic_to_png(path: str, tmp: str) -> str:
    """pillow-heif читает HEIC; конвертируем в PNG, чтобы ffmpeg точно взял."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".heic", ".heif"):
        return path
    from PIL import Image
    import pillow_heif
    pillow_heif.register_heif_opener()
    out = os.path.join(tmp, os.path.basename(path) + ".png")
    Image.open(path).convert("RGB").save(out)
    return out


def even(n):  # ffmpeg любит чётные размеры
    return int(n) // 2 * 2


def build_beat(i, beat, srcdir, tmp, W, H, fps, font):
    """Собрать один нормализованный сегмент beat_i.mp4."""
    src = os.path.join(srcdir, beat["src"])
    if not os.path.exists(src):
        raise SystemExit(f"[beat {i}] нет исходника: {src}")
    speed = float(beat.get("speed", 1.0))
    motion = beat.get("motion", "none")
    seg = os.path.join(tmp, f"beat_{i:02d}.mp4")

    # длительность на таймлайне
    if is_image(src):
        dur = float(beat.get("dur", 2.0))
        src = heic_to_png(src, tmp)
    else:
        tin, tout = float(beat.get("in", 0)), float(beat.get("out", 2))
        dur = round((tout - tin) / speed, 3)

    inputs = []
    vf_src = "[0:v]"
    if is_image(src):
        inputs += ["-loop", "1", "-t", f"{dur}", "-i", src]
    else:
        inputs += ["-ss", f"{beat['in']}", "-to", f"{beat['out']}", "-i", src]
    # тихая дорожка-запаска
    inputs += ["-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=44100:cl=stereo"]
    sil_idx = 1

    # ── видеоцепочка ──
    fill = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if is_image(src):
        # Ken Burns: апскейлим, затем zoompan
        z = "kenburns_out" if motion == "kenburns_out" else "kenburns_in"
        big_w, big_h = even(W * 2), even(H * 2)
        frames = max(1, int(dur * fps))
        if z == "kenburns_in":
            zexpr = "min(zoom+0.0010,1.18)"
        else:
            zexpr = "if(lte(zoom,1.0),1.18,max(zoom-0.0010,1.0))"
        vchain = (f"[0:v]scale={big_w}:{big_h}:force_original_aspect_ratio=increase,"
                  f"crop={big_w}:{big_h},zoompan=z='{zexpr}':d={frames}:"
                  f"s={W}x{H}:fps={fps},format=yuv420p[vbase]")
    else:
        pts = f"setpts=PTS/{speed}," if speed != 1.0 else ""
        punch = ""
        if motion == "punch":
            amt = float(beat.get("punch", 1.06))
            punch = f"scale={even(W*amt)}:{even(H*amt)},crop={W}:{H},"
        vchain = f"[0:v]{pts}{fill},{punch}fps={fps},format=yuv420p[vbase]"

    # ── аудиоцепочка ──
    keep = beat.get("audio", "keep") == "keep" and not is_image(src) and has_audio(os.path.join(srcdir, beat["src"]))
    if keep:
        atempo = f"atempo={speed}," if speed != 1.0 else ""
        achain = f"[0:a]{atempo}aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"
        amap = "[aout]"
    else:
        achain = f"[{sil_idx}:a]aresample=44100[aout]"
        amap = "[aout]"

    filt = vchain + ";" + achain
    vmap = "[vbase]"

    # ── текст (Pillow → overlay) ──
    txt = beat.get("text")
    text_png = None
    if txt:
        text_png = os.path.join(tmp, f"cap_{i:02d}.png")
        render_caption(txt.get("lines", []), highlight=txt.get("highlight"),
                       out_path=text_png, w=W, h=H, pos=txt.get("pos", "lower"),
                       font_path=font, font_size=int(txt.get("size", 84)))
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur}", "-i", text_png]
        cap_idx = 2  # 0=src,1=silence,2=caption (зациклен на длину beat'а)
        filt += (f";[{cap_idx}:v]format=rgba,fade=in:st=0:d=0.12:alpha=1[cap];"
                 f"{vmap}[cap]overlay=0:0:format=auto[vtxt]")
        vmap = "[vtxt]"

    cmd = [FFMPEG, "-y", *inputs, "-filter_complex", filt,
           "-map", vmap, "-map", amap, "-t", f"{dur}",
           "-r", f"{fps}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
           "-movflags", "+faststart", seg]
    run(cmd)
    return seg, dur


def concat(segs, tmp, out):
    lst = os.path.join(tmp, "concat.txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write(f"file '{os.path.abspath(s)}'\n")
    # переэнкод (сегменты одинаковы, но так надёжнее склейки разных длительностей)
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", out])


def add_music(video, music, gain_db, tmp, out, total_dur):
    run([FFMPEG, "-y", "-i", video, "-i", music, "-filter_complex",
         f"[1:a]volume={gain_db}dB,afade=out:st={max(0,total_dur-1.2)}:d=1.2[m];"
         f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,dynaudnorm[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", out])


def main():
    ap = argparse.ArgumentParser(description="Reels montage engine (EDL → mp4)")
    ap.add_argument("--edl", required=True)
    ap.add_argument("--src", default="montage/sources")
    ap.add_argument("--out", default="montage/out/reel.mp4")
    ap.add_argument("--font", default=None)
    args = ap.parse_args()

    with open(args.edl, encoding="utf-8") as f:
        edl = json.load(f)
    out_cfg = edl.get("output", {})
    W = even(out_cfg.get("w", 1080))
    H = even(out_cfg.get("h", 1920))
    fps = int(out_cfg.get("fps", 30))
    font = find_font(args.font)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    print(f"→ выход {W}x{H}@{fps}, шрифт: {font}")
    with tempfile.TemporaryDirectory() as tmp:
        segs, total = [], 0.0
        for i, beat in enumerate(edl["beats"]):
            seg, dur = build_beat(i, beat, args.src, tmp, W, H, fps, font)
            segs.append(seg); total += dur
            print(f"  ✓ beat {i:02d}  {beat['src'][:34]:34}  {dur:>5.2f}s  «{(beat.get('text') or {}).get('lines',[''])[0][:24]}»")
        base = os.path.join(tmp, "concat.mp4")
        concat(segs, tmp, base)
        music = edl.get("music", {})
        mfile = music.get("file")
        if mfile and os.path.exists(os.path.join(args.src, mfile)):
            add_music(base, os.path.join(args.src, mfile), music.get("gain_db", -18), tmp, args.out, total)
            print("  ✓ музыкальная подложка подмешана")
        else:
            os.replace(base, args.out)
            if mfile:
                print(f"  ⚠ музыка '{mfile}' не найдена в {args.src} — рендер без подложки")
    print(f"\n✅ готово: {args.out}  (~{total:.1f}s, {len(segs)} склеек)")


if __name__ == "__main__":
    main()
