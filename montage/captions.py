"""Рендер стилизованных подписей/хуков в PNG для наложения на ролик.

drawtext в статической сборке ffmpeg отсутствует, поэтому текст рисуем через
Pillow (полный контроль: жирный шрифт, белый + красная подсветка ключевого
слова, фон-плашка для читаемости), а ffmpeg накладывает готовый PNG через overlay.
"""
from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont

RED    = (232, 0, 10, 255)     # фирменный красный платформы
WHITE  = (240, 240, 245, 255)
SHADOW = (0, 0, 0, 190)
BOX    = (9, 9, 11, 150)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def find_font(explicit: str | None = None) -> str:
    if explicit and os.path.exists(explicit):
        return explicit
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("Не найден жирный TTF-шрифт. Укажи путь через font_path/--font")


def render_caption(lines, highlight=None, out_path="cap.png", w=1080, h=1920,
                   pos="lower", font_path=None, font_size=84, box=True):
    """Нарисовать подпись (1–3 строки) на прозрачном холсте wxh.

    lines     — список строк (по ≤4 слова, как для Reels-субтитров)
    highlight — слово, которое подсветить красным (без учёта регистра/пунктуации)
    pos       — 'lower' (нижняя треть), 'center' (хук), 'upper'
    """
    if isinstance(lines, str):
        lines = [lines]
    font_path = find_font(font_path)
    font = ImageFont.truetype(font_path, font_size)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    hl = (highlight or "").strip().lower()

    line_h = int(font_size * 1.28)
    total_h = line_h * len(lines)
    if pos == "center":
        y0 = (h - total_h) // 2
    elif pos == "upper":
        y0 = int(h * 0.15)
    else:
        y0 = int(h * 0.60)

    space = d.textlength(" ", font=font)
    for i, ln in enumerate(lines):
        words = ln.split()
        if not words:
            continue
        sizes = [d.textlength(wd, font=font) for wd in words]
        tw = sum(sizes) + space * (len(words) - 1)
        x = (w - tw) / 2
        y = y0 + i * line_h
        if box:
            pad = 24
            d.rounded_rectangle([x - pad, y - 12, x + tw + pad, y + font_size + 18],
                                radius=20, fill=BOX)
        cx = x
        for wd, wdw in zip(words, sizes):
            key = wd.strip(".,!?—:;«»\"'()").lower()
            color = RED if hl and key == hl else WHITE
            d.text((cx + 3, y + 4), wd, font=font, fill=SHADOW)  # тень
            d.text((cx, y), wd, font=font, fill=color)
            cx += wdw + space
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    # быстрый自-тест
    render_caption(["ОШТРАФОВАЛИ", "за СОСИСКИ"], highlight="сосиски",
                   out_path="_cap_test.png", pos="center", font_size=96)
    print("saved _cap_test.png")
