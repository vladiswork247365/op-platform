"""Доступ к «заводу» (factory/): промпты, база знаний, стиль автора.

Сценарист берёт отсюда промпт + подмешивает знания о продукте/бренде и стиль автора,
чтобы писать точно, на бренде и «голосом» автора. Всё правится как обычный текст.
"""
from __future__ import annotations
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FACTORY = os.path.join(os.path.dirname(HERE), "factory")


def _read(path: str) -> str:
    try:
        return open(path, encoding="utf-8").read().strip()
    except Exception:
        return ""


def prompt(name: str = "scenarist") -> str:
    """Промпт из factory/prompts/<name>.md ('' если нет — сценарист возьмёт встроенный)."""
    return _read(os.path.join(FACTORY, "prompts", f"{name}.md"))


def knowledge() -> str:
    """Вся база знаний (factory/knowledge/*.md), склеенная в один текст."""
    d = os.path.join(FACTORY, "knowledge")
    if not os.path.isdir(d):
        return ""
    parts = [_read(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".md")]
    return "\n\n".join(p for p in parts if p)


def style() -> str:
    return _read(os.path.join(FACTORY, "style.md"))


def context() -> str:
    """Блок знаний + стиля для подмешивания в промпт сценариста."""
    out = []
    kn = knowledge()
    st = style()
    if kn:
        out.append("=== БАЗА ЗНАНИЙ (продукт/бренд/виральность) ===\n" + kn)
    if st:
        out.append("=== СТИЛЬ АВТОРА (пиши так) ===\n" + st)
    return "\n\n".join(out)
