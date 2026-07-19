"""Deterministic offline analyzer — keyword-overlap heuristic, no network.

Used for DRY_RUN, the E2E deploy check and the test-suite. Produces stable,
explainable scores so the whole pipeline can be exercised without an API key.
"""
from __future__ import annotations

import re

from ..config import Settings
from .base import AIProvider, AnalysisContext, AnalysisResult

_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD.findall(text or "")}


class MockAIProvider(AIProvider):
    name = "mock"

    def __init__(self, settings: Settings | None = None):
        self.s = settings

    def analyze(self, ctx: AnalysisContext) -> AnalysisResult:
        title_toks = _tokens(ctx.title)
        desc_toks = _tokens(ctx.description)
        haystack = title_toks | desc_toks

        # Title match: any target/alt title term present in the vacancy title.
        wanted_title = set()
        for t in ctx.target_titles + ctx.alt_titles:
            wanted_title |= _tokens(t)
        title_match = 100 if (wanted_title & title_toks) else (
            60 if (wanted_title & haystack) else 20
        )

        # Skills match: fraction of profile skills present in the text.
        skills = [s for s in ctx.skills if s.strip()]
        if skills:
            hit = sum(1 for s in skills if _tokens(s) & haystack)
            skills_match = round(100 * hit / len(skills))
        else:
            # Fall back to resume overlap when no explicit skills configured.
            resume_toks = _tokens(ctx.resume_text)
            overlap = resume_toks & desc_toks
            skills_match = min(100, len(overlap) * 8) if resume_toks else 50

        # Experience: light heuristic from the resume text length / overlap.
        experience_match = 80 if _tokens(ctx.resume_text) & desc_toks else 50

        # Salary match relative to the candidate minimum.
        top = ctx.salary_to or ctx.salary_from or 0
        if ctx.min_salary <= 0:
            salary_match = 70
        elif top == 0:
            salary_match = 50  # salary not disclosed
        elif top >= ctx.min_salary:
            salary_match = 100
        else:
            salary_match = max(0, round(100 * top / ctx.min_salary))

        # Format match: remote preference vs schedule.
        fmt_text = f"{ctx.schedule} {ctx.employment}".lower()
        if ctx.remote_ok:
            format_match = 100 if ("удал" in fmt_text or "remote" in fmt_text) else 70
        else:
            format_match = 100

        reasons: list[str] = []
        risks: list[str] = []
        if title_match >= 80:
            reasons.append("Должность совпадает с целевой")
        else:
            risks.append("Название должности слабо совпадает")
        if skills_match >= 60:
            reasons.append("Ключевые навыки присутствуют")
        else:
            risks.append("Часть навыков не подтверждается описанием")
        if salary_match >= 100:
            reasons.append("Зарплата не ниже желаемой")
        elif salary_match < 60:
            risks.append("Зарплата ниже желаемой")
        if format_match >= 100 and ctx.remote_ok:
            reasons.append("Формат работы (удалённо) подходит")

        # Stop-words heavily penalise the score.
        stop_hit = any(_tokens(w) & haystack for w in ctx.stop_words if w.strip())
        if stop_hit:
            risks.append("Обнаружено стоп-слово")

        score = round(
            0.30 * title_match
            + 0.30 * skills_match
            + 0.15 * experience_match
            + 0.15 * salary_match
            + 0.10 * format_match
        )
        if stop_hit:
            score = min(score, 30)

        return AnalysisResult.validate(
            {
                "score": score,
                "experience_match": experience_match,
                "skills_match": skills_match,
                "title_match": title_match,
                "salary_match": salary_match,
                "format_match": format_match,
                "reasons": reasons,
                "risks": risks,
            },
            provider=self.name,
        )
