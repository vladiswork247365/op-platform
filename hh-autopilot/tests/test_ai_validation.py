import pytest

from app.ai.base import AnalysisContext, AnalysisResult
from app.ai.mock import MockAIProvider


def _ctx(**over):
    base = dict(
        title="Sales Manager", company="Acme", description="опыт продаж CRM B2B",
        area="Алматы", salary_from=500000, salary_to=800000, schedule="Удалённо",
        experience="1-3", employment="Полная", resume_text="опыт продаж CRM",
        target_titles=["Sales Manager"], alt_titles=[], skills=["CRM", "продаж"],
        remote_ok=True, min_salary=300000, stop_words=[],
    )
    base.update(over)
    return AnalysisContext(**base)


def test_validate_rejects_missing_score():
    with pytest.raises(ValueError):
        AnalysisResult.validate({"reasons": []}, "mock")


def test_validate_clamps_range():
    r = AnalysisResult.validate({"score": 250, "reasons": [], "risks": []}, "mock")
    assert r.score == 100


def test_validate_requires_lists():
    with pytest.raises(ValueError):
        AnalysisResult.validate({"score": 50, "reasons": "nope"}, "mock")


def test_mock_provider_shape_and_high_match():
    r = MockAIProvider().analyze(_ctx())
    assert 0 <= r.score <= 100
    assert r.score >= 85  # strong match under this profile
    assert isinstance(r.reasons, list) and isinstance(r.risks, list)


def test_stop_word_caps_score():
    r = MockAIProvider().analyze(_ctx(stop_words=["продаж"]))
    assert r.score <= 30
