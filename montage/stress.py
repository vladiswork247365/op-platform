#!/usr/bin/env python3
"""Русские ударения для TTS: проставляем ударение ПЕРЕД отправкой в ElevenLabs.

Зачем: ElevenLabs часто путает ударение в русском (догово́р→до́говор, звони́т→зво́нит,
ката́лог→катало́г). Мы заранее ставим знак ударения — комбинируемый акут U+0301 ПОСЛЕ
ударной гласной (а́, о́, е́, и́, у́, ы́, э́, ю́, я́) — этот знак ElevenLabs уважает и читает
верно. Для СУБТИТРОВ знак убираем (strip), чтобы он не висел чёрточкой над буквой.

Три уровня, мягкая деградация (ничего настраивать не обязательно):
  1) RUAccent (нейромодель + словарь, COLING-2025) — снимает даже омографы по контексту
     (за́мок/замо́к). Ставится один раз:  pip install ruaccent
     Модель качается сама при первом запуске. Лучшее качество.
  2) Встроенный словарь montage/stress_dict.json + твои поправки stress_overrides.json —
     работает из коробки без установок, заточен под лексику отдела продаж.
  3) Ничего нет — вернём текст как есть (ролик соберётся, просто без коррекции).

Выключить: STRESS=off в montage/.env.  Только словарь (без RUAccent): STRESS_ENGINE=dict.
Только стандартная библиотека (+ ruaccent, если он установлен).
"""
from __future__ import annotations
import json
import os
import re
import sys

ACUTE = "́"                      # U+0301 — знак ударения, который уважает ElevenLabs
_GRAVE = "̀"                     # иногда встречается вместо акута — тоже вычищаем в strip
_VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
_VSET = set(_VOWELS)

HERE = os.path.dirname(os.path.abspath(__file__))
_DICT_PATH = os.path.join(HERE, "stress_dict.json")
_OVERRIDES_PATH = os.path.join(HERE, "stress_overrides.json")

_dict = None
_ruaccent = None
_ruaccent_tried = False

_WORD_RE = re.compile(r"[А-Яа-яЁё]+")


def strip(text: str) -> str:
    """Убрать знаки ударения из строки (для субтитров/логов/показа автору)."""
    return (text or "").replace(ACUTE, "").replace(_GRAVE, "")


def _off() -> bool:
    # ПО УМОЛЧАНИЮ ВЫКЛЮЧЕНО. Знак ударения U+0301 на некоторых клон-голосах ElevenLabs
    # ломает произношение (тянет гласные, «баааляяя»). Включить осознанно: STRESS=on.
    return os.environ.get("STRESS", "off").strip().lower() not in ("on", "1", "yes", "true")


def _load_dict() -> dict:
    """Слить базовый словарь + пользовательские поправки. {слово: № ударной гласной (1-based)}."""
    global _dict
    if _dict is not None:
        return _dict
    d = {}
    for p in (_DICT_PATH, _OVERRIDES_PATH):          # overrides перекрывают базу
        try:
            raw = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for k, v in raw.items():
            if not k or k.startswith("_"):           # служебные ключи (_comment) пропускаем
                continue
            try:
                d[k.lower()] = int(v)
            except (TypeError, ValueError):
                pass
    _dict = d
    return d


def _load_ruaccent():
    """Лениво поднять RUAccent, если он установлен и не запрещён (STRESS_ENGINE=dict)."""
    global _ruaccent, _ruaccent_tried
    if _ruaccent_tried:
        return _ruaccent
    _ruaccent_tried = True
    if os.environ.get("STRESS_ENGINE", "").strip().lower() == "dict":
        return None
    try:
        from ruaccent import RUAccent
        acc = RUAccent()
        acc.load(omograph_model_size=os.environ.get("RUACCENT_MODEL", "turbo3.1"),
                 use_dictionary=True, tiny_mode=False)
        _ruaccent = acc
        sys.stderr.write("[stress] RUAccent загружен — ударения по нейромодели\n")
    except Exception as e:                            # нет пакета/модели/сети — тихо на словарь
        _ruaccent = None
        if os.environ.get("STRESS_DEBUG"):
            sys.stderr.write(f"[stress] RUAccent недоступен ({type(e).__name__}): {str(e)[:120]}\n")
    return _ruaccent


def _mark_by_index(token: str, vpos: int) -> str:
    """Вставить U+0301 после vpos-й (1-based) гласной токена."""
    if vpos < 1:
        return token
    seen = 0
    for i, ch in enumerate(token):
        if ch in _VSET:
            seen += 1
            if seen == vpos:
                return token[:i + 1] + ACUTE + token[i + 1:]
    return token


def _dict_accentize(text: str) -> str:
    d = _load_dict()
    if not d:
        return text

    def repl(m):
        w = m.group(0)
        low = w.lower()
        if ACUTE in w or "ё" in low:                  # ё уже несёт ударение — не трогаем
            return w
        vwls = [c for c in low if c in _VSET]
        if len(vwls) < 2:                             # моносиллаб — ударение не нужно
            return w
        vpos = d.get(low)
        return _mark_by_index(w, vpos) if isinstance(vpos, int) else w

    return _WORD_RE.sub(repl, text)


def _from_ruaccent(text: str) -> str:
    acc = _load_ruaccent()
    if not acc:
        return _dict_accentize(text)
    try:
        marked = acc.process_all(text)                # RUAccent ставит '+' ПЕРЕД ударной гласной
    except Exception:
        return _dict_accentize(text)
    # '+гласная' → 'гласная' + U+0301, остатки '+' вычищаем
    out = re.sub(r"\+([" + _VOWELS + r"])", lambda m: m.group(1) + ACUTE, marked)
    return out.replace("+", "")


def accentize(text: str) -> str:
    """Проставить ударения в тексте для TTS. Пусто/выключено/без кириллицы → как есть."""
    if not text or not text.strip() or _off():
        return text
    if not re.search(r"[А-Яа-яЁё]", text):
        return text
    try:
        return _from_ruaccent(text)
    except Exception as e:
        if os.environ.get("STRESS_DEBUG"):
            sys.stderr.write(f"[stress] {type(e).__name__}: {str(e)[:120]}\n")
        return text


def available() -> bool:
    """Есть ли чем ставить ударения (словарь или RUAccent)."""
    return bool(_load_dict()) or _load_ruaccent() is not None


def engine() -> str:
    """Каким движком ставим ударения сейчас — для статуса/лога."""
    if _off():
        return "off"
    if _load_ruaccent() is not None:
        return "ruaccent"
    return "dict" if _load_dict() else "none"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Проставить ударения в русском тексте (для TTS)")
    ap.add_argument("text", nargs="*", help="текст (или пусто — демо)")
    a = ap.parse_args()
    print("движок:", engine(), "| слов в словаре:", len(_load_dict()))
    demo = " ".join(a.text) or ("Договор на квартал: звонит клиент, аналитика "
                                "показывает конверсию, выручка отдела продаж растёт.")
    marked = accentize(demo)
    print("ДО :", demo)
    print("ПОСЛЕ:", marked)
    print("для субтитров (strip):", strip(marked))
