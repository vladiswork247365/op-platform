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

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",   # тяжёлый и чистый — лучше для субтитров
    "/Library/Fonts/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
]


def find_font(explicit: str | None = None) -> str:
    if explicit and os.path.exists(explicit):
        return explicit
    # 1) вшитый премиум-шрифт (montage/fonts/*.ttf|otf, напр. Montserrat) — в приоритете
    if os.path.isdir(FONTS_DIR):
        for f in sorted(os.listdir(FONTS_DIR)):
            if f.lower().endswith((".ttf", ".otf")):
                return os.path.join(FONTS_DIR, f)
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("Не найден жирный TTF-шрифт. Укажи путь через font_path/--font")


# тонкий/обычный шрифт для минимал-субтитров (как в топ-референсах — не жирный капс)
_LIGHT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",              # Mac — чистый тонкий сан-сериф
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",           # Linux
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def light_font(fallback: str | None = None) -> str:
    """Тонкий/обычный шрифт под минимал-субтитры. SUB_FONT — явный путь. Иначе: Medium/Regular
    из montage/fonts (если положишь), затем системный тонкий, иначе — переданный шрифт."""
    env = os.environ.get("SUB_FONT")
    if env and os.path.exists(env):
        return env
    if os.path.isdir(FONTS_DIR):                                  # вес не «bold/black/extra»
        for f in sorted(os.listdir(FONTS_DIR)):
            low = f.lower()
            if not low.endswith((".ttf", ".otf")):
                continue
            if any(b in low for b in ("bold", "black", "heavy", "extra", "semib")):
                continue
            if any(w in low for w in ("medium", "regular", "light", "book", "text")):
                return os.path.join(FONTS_DIR, f)
    for p in _LIGHT_CANDIDATES:
        if os.path.exists(p):
            return p
    return fallback or find_font()


def render_caption(lines, highlight=None, out_path="cap.png", w=1080, h=1920,
                   pos="lower", font_path=None, font_size=84, box=False, y_frac=None,
                   hl_color=RED, upper=True):   # выделение под бренд — фирменный красный
    """Нарисовать подпись (1–3 строки) на прозрачном холсте wxh.

    lines     — список строк (по ≤4 слова, как для Reels-субтитров)
    highlight — слово, которое подсветить красным (без учёта регистра/пунктуации)
    pos       — 'lower' (нижняя треть), 'center' (хук), 'upper'
    """
    if isinstance(lines, str):
        lines = [lines]
    font_path = find_font(font_path)
    # СТИЛЬ СУБТИТРОВ. minimal (по умолчанию) — как в топ-референсах: мелкие аккуратные
    # белые субтитры строчными, по центру, БЕЗ капса/красных плашек/боксов, лёгкая тень.
    # bold — прежний громкий вирал-стиль (крупный капс + красная подсветка). SUB_STYLE=bold.
    style = os.environ.get("SUB_STYLE", "minimal").strip().lower()
    minimal = style in ("minimal", "min", "clean", "premium")
    lower = False
    if minimal:
        upper, lower, box, highlight = False, True, False, None
        font_path = light_font(font_path)                          # тонкий шрифт, не жирный капс
        font_size = int(os.environ.get("SUB_SIZE", str(max(28, int(w * 0.044)))))  # ~47 на 1080
        if y_frac is None and pos != "center":
            y_frac = float(os.environ.get("SUB_Y", "0.63"))
    font = ImageFont.truetype(font_path, font_size)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    hl = (highlight or "").strip().lower()

    # перенос длинных строк по ширине при ПОСТОЯННОМ размере — чтобы субтитры не «скакали».
    max_w = w * 0.86

    def _fits(s):
        return d.textlength(s.upper() if upper else s, font=font) <= max_w

    wrapped = []
    for ln in lines:
        ws = ln.split()
        if not ws:
            continue
        cur = ""
        for wd in ws:
            t = (cur + " " + wd).strip()
            if cur and not _fits(t):
                wrapped.append(cur)
                cur = wd
            else:
                cur = t
        if cur:
            wrapped.append(cur)
    lines = wrapped or lines
    # только если ОДНО слово шире кадра — тогда уменьшаем шрифт (редкий случай), иначе размер постоянный
    widest = max((d.textlength((ln.upper() if upper else ln), font=font) for ln in lines), default=1.0)
    if widest > max_w:
        font_size = max(30, int(font_size * max_w / widest))
        font = ImageFont.truetype(font_path, font_size)

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

    stroke = 2 if minimal else max(4, font_size // 12)   # minimal — тонкая обводка + мягкая тень
    space = d.textlength(" ", font=font)
    for i, ln in enumerate(lines):
        words = [wd for wd in ln.split() if wd]
        if not words:
            continue
        disp = [wd.upper() if upper else (wd.lower() if lower else wd) for wd in words]
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
                # активное слово — в фирменной КРАСНОЙ плашке, БЕЛЫЙ текст (как лого «СИСТЕМА ОП»)
                px, py = int(font_size * 0.14), int(font_size * 0.04)
                d.rounded_rectangle([cx - px, y - py, cx + wdw + px, y + font_size + int(font_size * 0.24)],
                                    radius=int(font_size * 0.16), fill=hl_color)
                d.text((cx, y), wd, font=font, fill=WHITE,
                       stroke_width=max(2, stroke // 2), stroke_fill=(120, 0, 5, 255))
            elif minimal:
                # мягкая тень + тонкая обводка → чисто и читаемо на любом фоне (как в референсе)
                d.text((cx + 2, y + 3), wd, font=font, fill=(0, 0, 0, 120))
                d.text((cx, y), wd, font=font, fill=WHITE,
                       stroke_width=stroke, stroke_fill=(0, 0, 0, 200))
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
