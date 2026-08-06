#!/usr/bin/env python3
"""Премиальные анимированные субтитры пословно (стиль Hormozi/Bounce) через ASS + libass.

Каждое слово появляется с bounce-pop (scale 40→112→100), сильные слова — жёлтым.
Рендерится ffmpeg-фильтром subtitles= (libass есть в сборке). Кириллица — DejaVu Sans.

    build_ass(words, "cap.ass")               # words = [{'start','end','word'}]
    burn("in.mp4", "cap.ass", "out.mp4")
"""
from __future__ import annotations
import os
import subprocess

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
# сильные слова → жёлтая подсветка (ASS цвет = &HAABBGGRR)
POWER = set(("секрет ошибка никто почему деньги бесплатно главное результат проблема миллион "
             "никогда впервые лучший опасно важно фишка").split())
WHITE = "&H00FFFFFF"
YELLOW = "&H0000E5FF"   # жёлтый
OUTLINE = "&H00000000"


def _ts(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _norm(w: str) -> str:
    return "".join(c for c in w.lower() if c.isalnum())


def build_ass(words, out_path: str, W: int = 1080, H: int = 1920,
              fontsize: int = 118, margin_v: int = 620, font: str = "DejaVu Sans"):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,{font},{fontsize},{WHITE},{OUTLINE},&H64000000,-1,0,0,0,100,100,0,0,1,6,4,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for w in words:
        word = (w.get("word") or "").strip()
        if not word:
            continue
        st, en = float(w["start"]), max(float(w["end"]), float(w["start"]) + 0.18)
        col = YELLOW if _norm(word) in POWER else WHITE
        # bounce-pop + цвет активного слова
        anim = (r"{\an2" + rf"\c{col}\fscx40\fscy40\t(0,90,\fscx112\fscy112)\t(90,160,\fscx100\fscy100)" + "}")
        lines.append(f"Dialogue: 0,{_ts(st)},{_ts(en)},Pop,,0,0,0,,{anim}{word.upper()}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n")
    return out_path


def burn(video: str, ass_path: str, out: str):
    esc = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    subprocess.run([FF, "-y", "-i", video, "-vf", f"subtitles='{esc}'",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "copy", out], check=True, capture_output=True)
    return out


if __name__ == "__main__":
    ws, t = [], 0.0
    for word in "это ГЛАВНАЯ ошибка твоих продаж".split():
        ws.append({"start": round(t, 2), "end": round(t + 0.42, 2), "word": word}); t += 0.45
    build_ass(ws, "/tmp/_demo.ass")
    print("ASS собран → /tmp/_demo.ass")
