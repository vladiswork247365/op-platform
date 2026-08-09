"""Рендер графических плашек-акцентов (как в виральных Reels) в PNG для наложения.

Плашка = цветной прямоугольник с текстом: мелкий верхний лейбл, крупный заголовок
(1–2 строки), опциональная нижняя строка со стрелкой. Появляется в верхней части
кадра на сильных фразах («АНАЛИЗ 100% ЗВОНКОВ», «БЕСПЛАТНЫЙ ТЕСТ» и т.п.).

Палитра — как в референсе (жёлтая/голубая/розовая) + фирменная красная.
Текст авто-подбирается тёмным на светлых плашках и белым на тёмных.
"""
from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont

from captions import find_font

# bg (RGBA), автоопределение цвета текста по яркости фона
PALETTES = {
    "yellow": (255, 208, 10, 255),
    "cyan":   (45, 214, 236, 255),
    "pink":   (255, 40, 120, 255),
    "red":    (228, 0, 43, 255),
    "green":  (54, 210, 96, 255),
    "black":  (16, 16, 18, 255),
    "white":  (245, 245, 247, 255),
}
CYCLE = ["yellow", "cyan", "pink"]   # чередование по ходу ролика (как в референсе)


def _text_color(bg):
    r, g, b = bg[:3]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return (17, 17, 19, 255) if lum > 140 else (255, 255, 255, 255)


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if cur and draw.textlength(t, font=font) > max_w:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines or [text]


def render_card(headline, out_path="card.png", label="", sub="", color="yellow",
                w=1080, h=1920, y_frac=0.16, font_path=None, upper=True):
    """Нарисовать плашку на прозрачном холсте wxh. Возвращает (path, y_center_frac)."""
    bg = PALETTES.get(color, PALETTES["yellow"])
    fg = _text_color(bg)
    sub_fg = (fg[0], fg[1], fg[2], 210)
    font_path = find_font(font_path)
    if upper:
        headline, label, sub = headline.upper(), label.upper(), sub.upper()

    box_w = int(w * 0.90)
    pad_x, pad_y = int(w * 0.045), int(w * 0.035)
    inner = box_w - 2 * pad_x

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    f_head = ImageFont.truetype(font_path, 104)
    lines = _wrap(d, headline, f_head, inner)
    # если заголовок слишком широкий/длинный — ужимаем шрифт
    while (max(d.textlength(ln, font=f_head) for ln in lines) > inner or len(lines) > 2) and f_head.size > 48:
        f_head = ImageFont.truetype(font_path, f_head.size - 4)
        lines = _wrap(d, headline, f_head, inner)
    f_label = ImageFont.truetype(font_path, max(26, f_head.size // 3))
    f_sub = ImageFont.truetype(font_path, max(28, int(f_head.size * 0.38)))

    head_lh = int(f_head.size * 1.12)
    gap = int(f_head.size * 0.22)
    body_h = len(lines) * head_lh
    lab_h = (f_label.size + gap) if label else 0
    sub_h = (int(f_sub.size * 1.15) + gap) if sub else 0
    box_h = pad_y * 2 + lab_h + body_h + sub_h

    x0 = (w - box_w) // 2
    y0 = int(h * y_frac)
    radius = int(w * 0.03)
    d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=radius, fill=bg)

    cy = y0 + pad_y
    if label:
        lw = d.textlength(label, font=f_label)
        d.text(((w - lw) / 2, cy), label, font=f_label, fill=sub_fg)
        cy += f_label.size + gap
    for ln in lines:
        lw = d.textlength(ln, font=f_head)
        d.text(((w - lw) / 2, cy), ln, font=f_head, fill=fg)
        cy += head_lh
    if sub:
        sw = d.textlength(sub, font=f_sub)
        d.text(((w - sw) / 2, cy + gap // 2), sub, font=f_sub, fill=sub_fg)

    img.save(out_path)
    return out_path, round((y0 + box_h / 2) / h, 3)


if __name__ == "__main__":
    for i, (c, lab, hl, sb) in enumerate([
        ("yellow", "АНАЛИЗ", "100% ЗВОНКОВ", "→ и чатов"),
        ("cyan", "самое важное", "вся сделка целиком", "→ не один контакт"),
        ("pink", "риск найден", "уведомление сразу", "→ собственник · РОП · менеджер"),
        ("red", "на любом отделе", "бесплатный тест", ""),
    ]):
        render_card(hl, out_path=f"_card_{i}.png", label=lab, sub=sb, color=c)
    print("saved _card_0..3.png")
