"""Deterministic in-memory source for offline dry-run, demos and tests.

No network. Produces a fixed catalogue that exercises every pipeline branch:
a strong match, a salary-gate reject, a stop-word reject, a title mismatch,
and a duplicate of the first item under a new id.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from .base import ApplyResult, RawVacancy, VacancySource

_D = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

CATALOG: list[RawVacancy] = [
    RawVacancy(
        external_id="MOCK-1001",
        title="Sales Manager",
        company="Acme Trade",
        url="https://example.com/v/1001",
        area="Алматы",
        salary_from=500000,
        salary_to=800000,
        salary_currency="KZT",
        schedule="Удалённо",
        experience="От 1 года до 3 лет",
        employment="Полная занятость",
        description=(
            "Ищем менеджера по продажам с опытом работы в B2B. "
            "Обязанности: ведение сделок, работа с CRM, выполнение плана. "
            "Требования: опыт продаж, коммуникабельность, знание воронки продаж."
        ),
        published_at=_D,
        contact_name="Айгуль",
        contact_phone="+7 701 000 00 00",
        contact_email="hr@acme.example",
    ),
    RawVacancy(
        external_id="MOCK-1002",
        title="Sales Manager (Junior)",
        company="LowPay LLP",
        url="https://example.com/v/1002",
        area="Алматы",
        salary_from=120000,
        salary_to=150000,
        salary_currency="KZT",
        schedule="Полный день",
        experience="Нет опыта",
        employment="Полная занятость",
        description="Продажи по холодной базе. Оклад маленький, но есть бонусы.",
        published_at=_D,
    ),
    RawVacancy(
        external_id="MOCK-1003",
        title="Sales Manager — сетевой маркетинг",
        company="MLM World",
        url="https://example.com/v/1003",
        area="Алматы",
        salary_from=400000,
        salary_to=900000,
        salary_currency="KZT",
        schedule="Свободный",
        employment="Частичная занятость",
        description="Приглашаем в команду сетевой маркетинг (MLM). Продажи БАДов.",
        published_at=_D,
    ),
    RawVacancy(
        external_id="MOCK-1004",
        title="Backend Python Developer",
        company="DevShop",
        url="https://example.com/v/1004",
        area="Алматы",
        salary_from=700000,
        salary_to=1200000,
        salary_currency="KZT",
        schedule="Удалённо",
        experience="От 3 до 6 лет",
        employment="Полная занятость",
        description="Разработка на Python/FastAPI. Требуется опыт бэкенда.",
        published_at=_D,
    ),
    # Duplicate of MOCK-1001 content under a fresh id (dedup-by-content case).
    RawVacancy(
        external_id="MOCK-1005",
        title="Sales Manager",
        company="Acme Trade",
        url="https://example.com/v/1005",
        area="Алматы",
        salary_from=500000,
        salary_to=800000,
        salary_currency="KZT",
        schedule="Удалённо",
        experience="От 1 года до 3 лет",
        employment="Полная занятость",
        description=(
            "Ищем менеджера по продажам с опытом работы в B2B. "
            "Обязанности: ведение сделок, работа с CRM, выполнение плана. "
            "Требования: опыт продаж, коммуникабельность, знание воронки продаж."
        ),
        published_at=_D,
    ),
]


class MockSource(VacancySource):
    name = "mock"

    def __init__(self, settings: Settings | None = None):
        self.s = settings

    def search(self, params: dict[str, Any]) -> list[RawVacancy]:
        per_page = int(params.get("per_page") or len(CATALOG))
        return [self._copy(v) for v in CATALOG[:per_page]]

    def fetch_detail(self, external_id: str) -> RawVacancy:
        for v in CATALOG:
            if v.external_id == external_id:
                return self._copy(v)
        raise KeyError(external_id)

    def apply(self, external_id: str, cover_letter: str) -> ApplyResult:
        return ApplyResult(ok=True, operation_id=f"mock-op-{external_id}",
                           response="mock accepted")

    def healthcheck(self) -> tuple[bool, str]:
        return True, "mock source ready"

    @staticmethod
    def _copy(v: RawVacancy) -> RawVacancy:
        # Return a shallow copy so callers can mutate without touching CATALOG.
        return RawVacancy(**{**v.__dict__})
