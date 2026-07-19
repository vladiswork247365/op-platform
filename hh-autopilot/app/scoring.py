"""Turn an AI analysis + profile into a final decision.

Hard profile constraints (e.g. a mandatory minimum salary) override the score:
they can force a REJECT even on a high score, but never force a MATCH.
"""
from __future__ import annotations

from .ai.base import AnalysisResult
from .models import Decision
from .sources.base import RawVacancy


def decide(
    rv: RawVacancy,
    analysis: AnalysisResult,
    profile: dict,
    auto_apply_min: int,
    review_min: int,
) -> tuple[Decision, str]:
    # Hard gate: mandatory minimum salary.
    if profile.get("mandatory_min_salary"):
        min_salary = int(profile.get("min_salary") or 0)
        top = rv.salary_to or rv.salary_from or 0
        if min_salary > 0 and top > 0 and top < min_salary:
            return Decision.REJECT, "обязательный минимум по зарплате не соблюдён"

    score = analysis.score
    if score >= auto_apply_min:
        return Decision.MATCH, "score >= порога авто-отклика"
    if score >= review_min:
        return Decision.REVIEW, "score в зоне ручной проверки"
    return Decision.REJECT, "score ниже порога"
