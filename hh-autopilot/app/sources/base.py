"""Abstract vacancy source. New job boards plug in as additional adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class RawVacancy:
    """Normalised vacancy shape shared by all source adapters."""

    external_id: str
    title: str = ""
    company: str = ""
    url: str = ""
    area: str = ""
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    salary_currency: str = ""
    schedule: str = ""
    experience: str = ""
    employment: str = ""
    description: str = ""
    published_at: Optional[datetime] = None
    contact_name: str = ""
    contact_phone: str = ""
    contact_email: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApplyResult:
    ok: bool
    operation_id: str = ""
    response: str = ""
    error: str = ""
    permanent: bool = False  # permanent errors must NOT be retried


class VacancySource(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, params: dict[str, Any]) -> list[RawVacancy]:
        """Return vacancies for the saved search params (list view)."""

    @abstractmethod
    def fetch_detail(self, external_id: str) -> RawVacancy:
        """Return the full vacancy (description + contacts when published)."""

    @abstractmethod
    def apply(self, external_id: str, cover_letter: str) -> ApplyResult:
        """Send an application through the official channel."""

    def healthcheck(self) -> tuple[bool, str]:
        """Return (ok, detail). Overridable; default assumes healthy."""
        return True, "ok"
