"""Типы роликов: у каждого свои правила монтажа и своя папка-библиотека.

Чтобы не было путаницы: продающие, экспертные, кейсы, лид-магниты и личные
хранятся раздельно (montage/library/<тип>/out) и монтируются по своим настройкам.
"""
from __future__ import annotations
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "library")

# порядок = порядок кнопок в Телеграме
TYPES = {
    "product":    {"title": "🔴 Продающий (ИИ-контроль)",   "dense": True,
                   "hint": "продукт/оффер: ОКК, панель для РОПов, риск срыва"},
    "expert":     {"title": "🎯 Экспертный (сист. продажи)", "dense": False,
                   "hint": "польза/авторитет: как строить системный отдел продаж"},
    "case":       {"title": "📈 Кейс / результат",           "dense": True,
                   "hint": "цифры и результат клиента"},
    "leadmagnet": {"title": "📘 Лид-магнит (книга)",         "dense": False,
                   "hint": "книга «Отдел продаж. Другой подход», гайды"},
    "personal":   {"title": "👤 Личный / блог",              "dense": False,
                   "hint": "личный бренд, за кадром, размышления"},
}
DEFAULT = "product"


def valid(key: str) -> bool:
    return key in TYPES


def title(key: str) -> str:
    return TYPES.get(key, {}).get("title", key)


def hint(key: str) -> str:
    return TYPES.get(key, {}).get("hint", "")


def dense_default(key: str) -> bool:
    return bool(TYPES.get(key, {}).get("dense"))


def out_dir(key: str) -> str:
    """Папка готовых роликов этого типа (создаётся при необходимости)."""
    p = os.path.join(LIB, key if valid(key) else DEFAULT, "out")
    os.makedirs(p, exist_ok=True)
    return p


def sources_dir(key: str) -> str:
    p = os.path.join(LIB, key if valid(key) else DEFAULT, "sources")
    os.makedirs(p, exist_ok=True)
    return p


def log_reel(key: str, brief: str, reel_path: str):
    """Дописать ролик в библиотеку типа (лог сценариев/ТЗ)."""
    try:
        base = os.path.join(LIB, key if valid(key) else DEFAULT)
        os.makedirs(base, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M")
        with open(os.path.join(base, "reels_log.md"), "a", encoding="utf-8") as f:
            f.write(f"- [{stamp}] {os.path.basename(reel_path)} — ТЗ: {(brief or '—')[:200]}\n")
    except Exception:
        pass
