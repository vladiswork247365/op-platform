"""HeadHunter adapter — official api.hh.ru (works for hh.ru and hh.kz via `area`).

Search and detail use the public API (no auth). Sending applications uses the
authenticated negotiations endpoint and requires an OAuth2 access token plus a
resume id. Contacts are read only when the employer has published them.

No CAPTCHA/antibot bypass is performed — only documented API endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import httpx

from ..config import Settings
from .base import ApplyResult, RawVacancy, VacancySource


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class HeadHunterSource(VacancySource):
    name = "headhunter"

    def __init__(self, settings: Settings):
        self.s = settings
        self.base = settings.hh_api_base.rstrip("/")
        self._headers = {"User-Agent": settings.hh_user_agent}

    def _client(self, auth: bool = False) -> httpx.Client:
        headers = dict(self._headers)
        if auth and self.s.hh_access_token:
            headers["Authorization"] = f"Bearer {self.s.hh_access_token}"
        return httpx.Client(base_url=self.base, headers=headers, timeout=25.0)

    # ── search ─────────────────────────────────────────────────────────────
    def search(self, params: dict[str, Any]) -> list[RawVacancy]:
        query: dict[str, Any] = {"per_page": params.get("per_page", 20), "page": 0}
        for src_key, hh_key in (
            ("search_text", "text"),
            ("search_area", "area"),
            ("search_experience", "experience"),
            ("search_employment", "employment"),
            ("search_schedule", "schedule"),
            ("search_salary", "salary"),
        ):
            val = params.get(src_key)
            if val not in (None, "", []):
                query[hh_key] = val
        with self._client() as c:
            resp = c.get("/vacancies", params=query)
            resp.raise_for_status()
            data = resp.json()
        return [self._from_list_item(item) for item in data.get("items", [])]

    def _from_list_item(self, item: dict[str, Any]) -> RawVacancy:
        salary = item.get("salary") or {}
        return RawVacancy(
            external_id=str(item.get("id", "")),
            title=item.get("name", "") or "",
            company=(item.get("employer") or {}).get("name", "") or "",
            url=item.get("alternate_url", "") or "",
            area=(item.get("area") or {}).get("name", "") or "",
            salary_from=salary.get("from"),
            salary_to=salary.get("to"),
            salary_currency=salary.get("currency") or "",
            schedule=(item.get("schedule") or {}).get("name", "") or "",
            experience=(item.get("experience") or {}).get("name", "") or "",
            employment=(item.get("employment") or {}).get("name", "") or "",
            description=item.get("snippet", {}).get("responsibility", "") or "",
            published_at=_parse_dt(item.get("published_at")),
            raw=item,
        )

    # ── detail ─────────────────────────────────────────────────────────────
    def fetch_detail(self, external_id: str) -> RawVacancy:
        with self._client() as c:
            resp = c.get(f"/vacancies/{external_id}")
            resp.raise_for_status()
            data = resp.json()
        rv = self._from_list_item(data)
        # Full description (HTML) and key skills.
        desc = data.get("description", "") or ""
        skills = ", ".join(s.get("name", "") for s in data.get("key_skills", []) or [])
        rv.description = (desc + ("\nKey skills: " + skills if skills else "")).strip()
        # Contacts, only when the employer published them.
        contacts = data.get("contacts") or {}
        if contacts:
            rv.contact_name = contacts.get("name", "") or ""
            rv.contact_email = contacts.get("email", "") or ""
            phones = contacts.get("phones") or []
            if phones:
                p = phones[0]
                rv.contact_phone = p.get("formatted") or (
                    f"+{p.get('country', '')}{p.get('city', '')}{p.get('number', '')}"
                )
        rv.raw = data
        return rv

    # ── apply ──────────────────────────────────────────────────────────────
    def apply(self, external_id: str, cover_letter: str) -> ApplyResult:
        if not self.s.hh_access_token or not self.s.hh_resume_id:
            return ApplyResult(
                ok=False,
                error="HH access token / resume id not configured",
                permanent=True,
            )
        data = {
            "vacancy_id": external_id,
            "resume_id": self.s.hh_resume_id,
            "message": cover_letter,
        }
        try:
            with self._client(auth=True) as c:
                resp = c.post("/negotiations", data=data)
        except httpx.RequestError as exc:  # network — temporary
            return ApplyResult(ok=False, error=f"network: {exc}", permanent=False)

        if resp.status_code in (200, 201, 204):
            op = resp.headers.get("Location", "") or f"neg:{external_id}"
            return ApplyResult(ok=True, operation_id=op, response=resp.text[:2000])
        # 429 / 5xx are transient; other 4xx are permanent.
        permanent = not (resp.status_code == 429 or resp.status_code >= 500)
        return ApplyResult(
            ok=False,
            error=f"HTTP {resp.status_code}: {resp.text[:500]}",
            permanent=permanent,
        )

    # ── health ─────────────────────────────────────────────────────────────
    def healthcheck(self) -> tuple[bool, str]:
        try:
            with self._client() as c:
                resp = c.get("/vacancies", params={"per_page": 0})
            if resp.status_code == 200:
                return True, "hh api reachable"
            return False, f"hh api HTTP {resp.status_code}"
        except httpx.RequestError as exc:
            return False, f"hh api unreachable: {exc}"
