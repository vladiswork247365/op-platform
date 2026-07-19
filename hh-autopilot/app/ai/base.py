"""AI provider contract and the validated analysis result."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalysisContext:
    title: str
    company: str
    description: str
    area: str
    salary_from: int | None
    salary_to: int | None
    schedule: str
    experience: str
    employment: str
    resume_text: str
    target_titles: list[str]
    alt_titles: list[str]
    skills: list[str]
    remote_ok: bool
    min_salary: int
    stop_words: list[str]


@dataclass
class AnalysisResult:
    score: int
    experience_match: int = 0
    skills_match: int = 0
    title_match: int = 0
    salary_match: int = 0
    format_match: int = 0
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    provider: str = "mock"

    @staticmethod
    def _clamp(v: Any) -> int:
        try:
            return max(0, min(100, int(round(float(v)))))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def validate(cls, data: dict[str, Any], provider: str) -> "AnalysisResult":
        """Validate/normalise a raw provider dict into a safe result.

        Raises ValueError if the payload is not the expected shape — the
        pipeline turns that into a NEEDS_ATTENTION item rather than guessing.
        """
        if not isinstance(data, dict) or "score" not in data:
            raise ValueError("AI response missing 'score'")
        reasons = data.get("reasons") or []
        risks = data.get("risks") or []
        if not isinstance(reasons, list) or not isinstance(risks, list):
            raise ValueError("AI 'reasons'/'risks' must be lists")
        return cls(
            score=cls._clamp(data.get("score")),
            experience_match=cls._clamp(data.get("experience_match")),
            skills_match=cls._clamp(data.get("skills_match")),
            title_match=cls._clamp(data.get("title_match")),
            salary_match=cls._clamp(data.get("salary_match")),
            format_match=cls._clamp(data.get("format_match")),
            reasons=[str(r)[:300] for r in reasons][:8],
            risks=[str(r)[:300] for r in risks][:8],
            provider=provider,
        )


class AIProvider(ABC):
    name: str = "base"

    @abstractmethod
    def analyze(self, ctx: AnalysisContext) -> AnalysisResult:
        ...

    def healthcheck(self) -> tuple[bool, str]:
        return True, "ok"
