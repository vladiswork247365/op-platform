"""Cheap deterministic prefilter — runs BEFORE the AI to save cost.

Obviously unsuitable vacancies are dropped without an AI call. Returns
(passed, reason). `reason` is populated only when the vacancy is rejected.
"""
from __future__ import annotations

import re

from .sources.base import RawVacancy

_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD.findall(text or "")}


def prefilter(rv: RawVacancy, profile: dict) -> tuple[bool, str]:
    hay_title = _tokens(rv.title)
    hay_all = hay_title | _tokens(rv.description)

    # Stop words → immediate drop.
    for w in profile.get("stop_words") or []:
        if w.strip() and (_tokens(w) & hay_all):
            return False, f"стоп-слово: {w}"

    # Required keywords (all must appear somewhere).
    for w in profile.get("required_keywords") or []:
        if w.strip() and not (_tokens(w) & hay_all):
            return False, f"нет обязательного слова: {w}"

    # Title relevance: at least one target/alt title term must appear
    # somewhere, when target titles are configured.
    targets = (profile.get("target_titles") or []) + (profile.get("alt_titles") or [])
    if targets:
        wanted: set[str] = set()
        for t in targets:
            wanted |= _tokens(t)
        if wanted and not (wanted & hay_all):
            return False, "должность не относится к целевым"

    # Hard salary gate (only when the user marked min salary as mandatory).
    if profile.get("mandatory_min_salary"):
        min_salary = int(profile.get("min_salary") or 0)
        top = rv.salary_to or rv.salary_from or 0
        if min_salary > 0 and top > 0 and top < min_salary:
            return False, f"зарплата ниже обязательного минимума ({min_salary})"

    return True, ""
