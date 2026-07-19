"""Vacancy source adapters."""
from __future__ import annotations

from ..config import Settings
from .base import RawVacancy, VacancySource
from .headhunter import HeadHunterSource
from .mock import MockSource


def build_source(settings: Settings) -> VacancySource:
    if settings.vacancy_source == "headhunter":
        return HeadHunterSource(settings)
    return MockSource(settings)


__all__ = ["RawVacancy", "VacancySource", "HeadHunterSource", "MockSource", "build_source"]
