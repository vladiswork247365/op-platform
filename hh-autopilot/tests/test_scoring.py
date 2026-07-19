from app.ai.base import AnalysisResult
from app.models import Decision
from app.scoring import decide
from app.sources.mock import CATALOG

BY_ID = {v.external_id: v for v in CATALOG}


def _res(score):
    return AnalysisResult(score=score)


def _profile(**over):
    base = {"mandatory_min_salary": False, "min_salary": 0}
    base.update(over)
    return base


def test_thresholds():
    rv = BY_ID["MOCK-1001"]
    assert decide(rv, _res(90), _profile(), 85, 65)[0] is Decision.MATCH
    assert decide(rv, _res(70), _profile(), 85, 65)[0] is Decision.REVIEW
    assert decide(rv, _res(40), _profile(), 85, 65)[0] is Decision.REJECT


def test_hard_salary_gate_overrides_high_score():
    # MOCK-1002 top salary 150k < mandatory 300k -> REJECT even at score 100.
    rv = BY_ID["MOCK-1002"]
    decision, reason = decide(
        rv, _res(100), _profile(mandatory_min_salary=True, min_salary=300000), 85, 65
    )
    assert decision is Decision.REJECT and "минимум" in reason
