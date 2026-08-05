#!/usr/bin/env python3
"""Реестр виральных инструментов Reels-фабрики + авто-подбор под ролик.

Каждый инструмент — реальная техника, реализованная в движке (montage/*).
ИИ/пайплайн вызывает recommend(signals) → набор инструментов для максимальной
«залетаемости» с обоснованием. Каталог выгружается в viral.json для дашборда.
"""
from __future__ import annotations
import json
import os

TOOLS = [
    {"key": "hook3s",        "name": "Хук 0–3 с",              "impact": 10, "does": "Крючок в первые 3 сек — решает досмотр",         "when": "всегда",               "engine": "auto_edl (hook) + reels.json score"},
    {"key": "auto_cut",      "name": "Авто-динамика",          "impact": 9,  "does": "auto-editor режет паузы/тишину, держит темп",   "when": "есть речь",            "engine": "dynamic_cut.py"},
    {"key": "word_subs",     "name": "Пословные субтитры",     "impact": 9,  "does": "Субтитры по словам с подсветкой (80% без звука)", "when": "есть речь",          "engine": "transcribe.py + render captions"},
    {"key": "beat_sync",     "name": "Нарезка в бит",          "impact": 8,  "does": "Склейки на бит музыки — гипнотизирует",         "when": "есть музыка",          "engine": "beat_sync.py (librosa)"},
    {"key": "virality_score","name": "Оценка удержания",       "impact": 8,  "does": "Скоринг вариантов A/B, выбор лучшего",          "when": "всегда",               "engine": "reels.json rubric + virality_predictor"},
    {"key": "zoom_punch",    "name": "Зум-панч / зум камеры",  "impact": 7,  "does": "Движение в кадре против статики",               "when": "статичные/длинные куски", "engine": "render motion"},
    {"key": "broll_stock",   "name": "B-roll / сток в тему",   "impact": 7,  "does": "Наслоение кадров по смыслу речи",               "when": "есть ключевые слова + Pexels", "engine": "stock.py"},
    {"key": "loop_cta",      "name": "CTA-петля",              "impact": 7,  "does": "Замыкание на начало → реплеи",                 "when": "всегда",               "engine": "auto_edl CTA"},
    {"key": "transitions",   "name": "Переходы",               "impact": 6,  "does": "Плавные/резкие переходы на сменах сцен",        "when": "смена сцены",          "engine": "render xfade"},
    {"key": "boomerang",     "name": "Бумеранг (туда-сюда)",   "impact": 6,  "does": "Акцент-перемотка на ключевом моменте",         "when": "короткий акцент",      "engine": "render motion"},
    {"key": "loudness",      "name": "Громкость под соцсети",  "impact": 6,  "does": "EBU -14 LUFS — не тише ленты",                 "when": "всегда",               "engine": "render finalize"},
    {"key": "color_punch",   "name": "Цветовой панч",          "impact": 5,  "does": "Контраст/сочность/резкость",                   "when": "всегда",               "engine": "render finalize"},
]
TOOLS_BY_KEY = {t["key"]: t for t in TOOLS}


def edl_duration(edl):
    total = 0.0
    for b in edl.get("beats", []):
        if "in" in b:
            total += (float(b["out"]) - float(b["in"])) / float(b.get("speed", 1.0))
        else:
            total += float(b.get("dur", 0))
    return round(total, 1)


def signals_from_edl(edl, words=None, has_music=None):
    vids = [b for b in edl.get("beats", []) if "in" in b]
    static = sum(1 for b in vids if b.get("motion") in (None, "none"))
    return {
        "duration": edl_duration(edl),
        "has_speech": bool(words),
        "has_music": bool(edl.get("music")) if has_music is None else has_music,
        "has_keywords": bool(words),
        "static_ratio": round(static / len(vids), 2) if vids else 0.0,
    }


def recommend(signals):
    """→ [{tool, why, impact, name}] — какие инструменты включить под ролик."""
    picked = []

    def add(k, why):
        t = TOOLS_BY_KEY[k]
        picked.append({"tool": k, "name": t["name"], "impact": t["impact"], "why": why})

    for k in ("hook3s", "virality_score", "loop_cta", "loudness", "color_punch"):
        add(k, "база залетаемости")
    if signals.get("has_speech"):
        add("auto_cut", "убрать мёртвый воздух — держим темп")
        add("word_subs", "≈80% смотрят без звука")
    if signals.get("has_music"):
        add("beat_sync", "склейки в бит удерживают внимание")
    if signals.get("has_keywords"):
        add("broll_stock", "иллюстрируем смысл кадрами")
    if signals.get("duration", 0) >= 20 or signals.get("static_ratio", 0) > 0.4:
        add("zoom_punch", "разбиваем статику движением")
        add("transitions", "мягкие переходы на сменах")
    picked.sort(key=lambda x: -x["impact"])
    return picked


def dump_catalog(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"tools": TOOLS}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Виральный реестр / авто-подбор")
    ap.add_argument("--edl", help="показать рекомендации под EDL")
    ap.add_argument("--dump", help="выгрузить каталог в JSON")
    a = ap.parse_args()
    if a.dump:
        dump_catalog(a.dump)
        print("каталог →", a.dump)
    if a.edl:
        with open(a.edl, encoding="utf-8") as f:
            edl = json.load(f)
        sig = signals_from_edl(edl, words=None)
        print("сигналы:", sig)
        for r in recommend(sig):
            print(f"  [{r['impact']:>2}] {r['name']:26} — {r['why']}")
