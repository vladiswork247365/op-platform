"""Рендер стилизованных подписей/хуков в PNG для наложения на ролик.

drawtext в статической сборке ffmpeg отсутствует, поэтому текст рисуем через
Pillow (полный контроль: жирный шрифт, белый + красная подсветка ключевого
слова, фон-плашка для читаемости), а ffmpeg накладывает готовый PNG через overlay.
"""
from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont

RED     = (232, 0, 10, 255)      # фирменный красный платформы
WHITE   = (255, 255, 255, 255)
YELLOW  = (255, 214, 10, 255)    # выделение ключевого слова (стиль референса)
OUTLINE = (0, 0, 0, 240)         # жирная чёрная обводка букв
SHADOW  = (0, 0, 0, 190)
BOX     = (9, 9, 11, 150)
STRIP   = ".,!?—:;«»\"'()"

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
                   pos="lower", font_path=None, font_size=84, box=False, y_frac=None,
                   hl_color=YELLOW, upper=True):
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
    if y_frac is not None:
        # явная зона (например, рассчитанная по лицу) — центр блока на y_frac высоты
        y0 = int(h * float(y_frac)) - total_h // 2
    elif pos == "center":
        y0 = (h - total_h) // 2
    elif pos == "upper":
        y0 = int(h * 0.15)
    else:
        # нижняя безопасная зона по умолчанию: под лицом (говорящая голова обычно
        # вверху-центре), но выше зоны кнопок платформы. (было 0.60 — попадало на лицо)
        y0 = int(h * 0.74) - total_h // 2
    y0 = max(6, min(y0, h - total_h - 6))

    stroke = max(4, font_size // 12)      # жирная обводка под референс
    space = d.textlength(" ", font=font)
    for i, ln in enumerate(lines):
        words = [wd for wd in ln.split() if wd]
        if not words:
            continue
        disp = [wd.upper() if upper else wd for wd in words]
        sizes = [d.textlength(wd, font=font) for wd in disp]
        tw = sum(sizes) + space * (len(disp) - 1)
        x = (w - tw) / 2
        y = y0 + i * line_h
        if box:
            pad = 26
            d.rounded_rectangle([x - pad, y - 14, x + tw + pad, y + font_size + 20],
                                radius=22, fill=BOX)
        cx = x
        for orig, wd, wdw in zip(words, disp, sizes):
            key = orig.strip(STRIP).lower()
            if hl and key == hl:
                # активное слово — в жёлтой плашке, тёмный текст (стиль референса)
                px, py = int(font_size * 0.14), int(font_size * 0.04)
                d.rounded_rectangle([cx - px, y - py, cx + wdw + px, y + font_size + int(font_size * 0.24)],
                                    radius=int(font_size * 0.16), fill=hl_color)
                d.text((cx, y), wd, font=font, fill=(15, 15, 17, 255))
            else:
                d.text((cx, y), wd, font=font, fill=WHITE,
                       stroke_width=stroke, stroke_fill=OUTLINE)
            cx += wdw + space
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    # быстрый自-тест
    render_caption(["ОШТРАФОВАЛИ", "за СОСИСКИ"], highlight="сосиски",
                   out_path="_cap_test.png", pos="center", font_size=96)
    print("saved _cap_test.png")
