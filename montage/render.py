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
SFX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "studio", "sfx")


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


def _dims(path: str):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True)
    import re
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", p.stderr)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


_BARCROP: dict[str, str] = {}


def bars_crop(path: str) -> str:
    """Обрезка вшитых чёрных полос (letterbox/pillarbox). Возвращает 'crop=...,'
    или '' если полос нет. Кешируется по файлу."""
    if path in _BARCROP:
        return _BARCROP[path]
    res = ""
    try:
        import re
        from collections import Counter
        p = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-vf", "cropdetect=24:2:0",
                            "-frames:v", "90", "-f", "null", "-"], capture_output=True, text=True)
        crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", p.stderr)
        iw, ih = _dims(path)
        if crops and iw and ih:
            cw, ch, cx, cy = (int(x) for x in Counter(crops).most_common(1)[0][0])
            # применяем только если полосы значимые (>5% по высоте или ширине)
            if 0 < cw <= iw and 0 < ch <= ih and (ch < ih * 0.95 or cw < iw * 0.95):
                res = f"crop={cw}:{ch}:{cx}:{cy},"
    except Exception:
        res = ""
    _BARCROP[path] = res
    return res


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

    boomerang = (not is_image(src)) and motion == "boomerang"
    if boomerang:
        dur = round(dur * 2, 3)  # вперёд + реверс

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
    # сперва срезаем вшитые чёрные полосы (letterbox), потом заполняем 9:16
    bc = "" if is_image(src) else bars_crop(src)
    fill = f"{bc}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
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
                  f"s={W}x{H}:fps={fps},format=yuv420p,setsar=1[vbase]")
    else:
        pts = f"setpts=PTS/{speed}," if speed != 1.0 else ""
        mo = ""
        if motion == "punch":
            amt = float(beat.get("punch", 1.06))
            mo = f"scale={even(W*amt)}:{even(H*amt)},crop={W}:{H},"
        elif motion in ("zoomin", "zoomout"):  # зум камеры через zoompan (pzoom — накопление)
            zexpr = ("min(pzoom+0.0015,1.25)" if motion == "zoomin"
                     else "if(eq(on,0),1.25,max(pzoom-0.0015,1.0))")
            mo = (f"zoompan=z='{zexpr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"s={W}x{H}:fps={fps},")
        elif motion == "kick":  # панч-ин на резе с быстрым оседанием (виральный ритм)
            mo = (f"zoompan=z='max(1.0,1.12-on*0.009)':d=1:x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps},")
        if boomerang:  # перемотка туда-сюда: вперёд + реверс, звук глушим
            vchain = (f"[0:v]{fill},fps={fps},format=yuv420p,split[bf][bb];"
                      f"[bb]reverse[bbr];[bf][bbr]concat=n=2:v=1:a=0,setsar=1[vbase]")
        else:
            vchain = f"[0:v]{pts}{fill},fps={fps},{mo}format=yuv420p,setsar=1[vbase]"

    # ── аудиоцепочка ──
    keep = (beat.get("audio", "keep") == "keep" and not is_image(src) and not boomerang
            and has_audio(os.path.join(srcdir, beat["src"])))
    if keep:
        atempo = f"atempo={speed}," if speed != 1.0 else ""
        achain = f"[0:a]{atempo}aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"
        amap = "[aout]"
    else:
        achain = f"[{sil_idx}:a]aresample=44100[aout]"
        amap = "[aout]"

    filt = vchain + ";" + achain
    vmap = "[vbase]"

    # ── подписи: одиночный text ИЛИ анимированный трек captions (пословно) ──
    cues = beat.get("captions")
    if not cues and beat.get("text"):
        t = beat["text"]
        cues = [{"lines": t.get("lines", []), "highlight": t.get("highlight"),
                 "pos": t.get("pos", "lower"), "size": t.get("size", 84)}]  # без времени = весь beat
    if cues:
        cap_idx = 2  # 0=src, 1=silence, далее подписи
        for j, cue in enumerate(cues):
            png = os.path.join(tmp, f"cap_{i:02d}_{j:02d}.png")
            render_caption(cue.get("lines", []), highlight=cue.get("highlight"),
                           out_path=png, w=W, h=H, pos=cue.get("pos", "lower"),
                           font_path=font, font_size=int(cue.get("size", 84)),
                           y_frac=cue.get("yf"))
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur}", "-i", png]
            enable = ""
            if "t0" in cue:
                t0 = max(0.0, float(cue["t0"]))
                t1 = float(cue.get("t1", dur))
                enable = f":enable='between(t,{t0:.2f},{t1:.2f})'"
            filt += (f";[{cap_idx}:v]format=rgba[capin{j}];"
                     f"{vmap}[capin{j}]overlay=0:0{enable}[vtxt{j}]")
            vmap = f"[vtxt{j}]"
            cap_idx += 1

    cmd = [FFMPEG, "-y", *inputs, "-filter_complex", filt,
           "-map", vmap, "-map", amap, "-t", f"{dur}",
           "-r", f"{fps}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
           "-movflags", "+faststart", seg]
    run(cmd)
    return seg, dur


XFADE_TD = 0.28  # длительность мягкого перехода


def concat(segs, durs, transes, tmp, out, fps=30):
    """Склейка сегментов. Возвращает (join_times, total) — моменты стыков на итоговом
    таймлайне (для SFX) и реальную длительность (для затухания музыки)."""
    # «жёсткий рез» в xfade-цепочке должен длиться ≥ 2 кадров, иначе xfade короче кадра
    # ломается и обрывает цепочку (видео обрезается на первом клипе). Держим кадро-безопасно.
    td_cut = max(0.08, 2.0 / max(1, fps))
    # нет переходов → простая надёжная склейка встык (жёсткие резы = динамика)
    if not any(transes[1:]):
        lst = os.path.join(tmp, "concat.txt")
        with open(lst, "w") as f:
            for s in segs:
                f.write(f"file '{os.path.abspath(s)}'\n")
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lst,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", out])
        joins, acc = [], 0.0
        for dd in durs[:-1]:
            acc += dd
            joins.append(round(acc, 3))
        return joins, round(sum(durs), 3)
    # xfade-цепочка: cut = почти мгновенный переход, остальные — по типу beat'а.
    # ВАЖНО: xfade(видео) и acrossfade(аудио) в ОДНОМ графе несовместимы — у них разные
    # модели времени (offset vs последовательное потребление), ffmpeg упирается в
    # рассинхрон framesync («buffers queued» → аудио-энкодер падает). Поэтому делаем два
    # раздельных прохода (видео-only + аудио-only), затем мукс. Итоговые длительности
    # совпадают (sum(durs) − N·td), синхрон сохраняется.
    inputs = []
    for s in segs:
        inputs += ["-i", s]
    vf, af, joins = [], [], []
    vcur, acur, acc = "[0:v]", "[0:a]", durs[0]
    for i in range(1, len(segs)):
        t = transes[i]
        cut = t in (None, "cut")
        td = td_cut if cut else XFADE_TD
        trans = "fade" if cut else t
        off = max(0.0, acc - td)
        joins.append(round(off + td / 2, 3))   # середина перехода — точка «удара» SFX
        vl, al = f"[v{i}]", f"[a{i}]"
        vf.append(f"{vcur}[{i}:v]xfade=transition={trans}:duration={td}:offset={off:.3f}{vl}")
        af.append(f"{acur}[{i}:a]acrossfade=d={td}{al}")
        vcur, acur = vl, al
        acc = acc + durs[i] - td
    vonly = os.path.join(tmp, "concat_v.mp4")
    aonly = os.path.join(tmp, "concat_a.m4a")
    run([FFMPEG, "-y", *inputs, "-filter_complex", ";".join(vf), "-map", vcur, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", vonly])
    run([FFMPEG, "-y", *inputs, "-filter_complex", ";".join(af), "-map", acur, "-vn",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", aonly])
    run([FFMPEG, "-y", "-i", vonly, "-i", aonly, "-c", "copy", "-shortest",
         "-movflags", "+faststart", out])
    return joins, round(acc, 3)


def add_music(video, music, gain_db, tmp, out, total_dur):
    run([FFMPEG, "-y", "-i", video, "-i", music, "-filter_complex",
         f"[1:a]volume={gain_db}dB,afade=out:st={max(0,total_dur-1.2)}:d=1.2[m];"
         f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,dynaudnorm[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", out])


def mix_sfx(video, cut_times, out, sfx="whoosh.wav"):
    """Подмешать SFX на монтажных склейках (за 15 мс до реза — перезапуск внимания)."""
    path = os.path.join(SFX_DIR, sfx)
    if not os.path.exists(path) or not cut_times:
        return False
    n = len(cut_times)
    parts = ["[1:a]asplit=%d%s" % (n, "".join(f"[s{i}]" for i in range(n)))]
    for i, t in enumerate(cut_times):
        ms = max(0, int((t - 0.015) * 1000))
        parts.append(f"[s{i}]adelay={ms}|{ms}[a{i}]")
    parts.append("[0:a]" + "".join(f"[a{i}]" for i in range(n)) +
                 f"amix=inputs={n + 1}:normalize=0:duration=first[a]")
    run([FFMPEG, "-y", "-i", video, "-i", path, "-filter_complex", ";".join(parts),
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", out])
    return True


def finalize(src, out, total=0.0, progress=True, grayscale=False):
    """Финальный проход для «залетаемости»: громкость под соцсети (EBU -14 LUFS),
    цветовой панч (или ч/б грейд), лёгкая резкость."""
    if grayscale:
        # ч/б (серый) грейд: убрать цвет, поднять контраст — моно-мотивационный вид
        vf = "hue=s=0,eq=contrast=1.14:brightness=0.0,unsharp=5:5:0.4:5:5:0.0"
    else:
        vf = "eq=contrast=1.06:saturation=1.12:brightness=0.01,unsharp=5:5:0.4:5:5:0.0"
    if progress and total > 0:
        # тонкая красная полоса прогресса вверху — растёт по ходу ролика
        vf += (f",drawbox=x=0:y=0:h=10:w='iw*min(t/{total:.2f}\\,1)':"
               f"color=0xE8000A@0.95:t=fill")
    run([FFMPEG, "-y", "-i", src, "-vf", vf,
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", out])


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
        segs, durs, transes, total = [], [], [], 0.0
        for i, beat in enumerate(edl["beats"]):
            seg, dur = build_beat(i, beat, args.src, tmp, W, H, fps, font)
            segs.append(seg); durs.append(dur); transes.append(beat.get("transition"))
            total += dur
            print(f"  ✓ beat {i:02d}  {beat['src'][:30]:30}  {beat.get('motion','none'):8} {dur:>5.2f}s  «{(beat.get('text') or {}).get('lines',[''])[0][:20]}»")
        base = os.path.join(tmp, "concat.mp4")
        cut_times, total = concat(segs, durs, transes, tmp, base, fps=fps)
        music = edl.get("music", {})
        mfile = music.get("file")
        stage = base
        if mfile and os.path.exists(os.path.join(args.src, mfile)):
            stage = os.path.join(tmp, "mixed.mp4")
            add_music(base, os.path.join(args.src, mfile), music.get("gain_db", -18), tmp, stage, total)
            print("  ✓ музыкальная подложка подмешана")
        elif mfile:
            print(f"  ⚠ музыка '{mfile}' не найдена в {args.src} — рендер без подложки")
        # SFX-«вжух» на каждом стыке (и на жёстких резах, и на динамичных переходах)
        if cut_times:
            sfx_stage = os.path.join(tmp, "sfx.mp4")
            if mix_sfx(stage, cut_times, sfx_stage):
                stage = sfx_stage
                print(f"  ✓ SFX на {len(cut_times)} стыках (whoosh)")
        gray = bool(out_cfg.get("grayscale"))
        finalize(stage, args.out, total, progress=False, grayscale=gray)
        print(f"  ✓ финал: loudnorm -14 LUFS + {'ч/б грейд' if gray else 'цветовой панч'}")
    print(f"\n✅ готово: {args.out}  (~{total:.1f}s, {len(segs)} склеек)")


if __name__ == "__main__":
    main()
