from app.prefilter import prefilter
from app.sources.mock import CATALOG

BY_ID = {v.external_id: v for v in CATALOG}


def _profile(**over):
    base = {
        "stop_words": ["сетевой", "MLM"],
        "required_keywords": [],
        "target_titles": ["Sales Manager", "менеджер по продажам"],
        "alt_titles": [],
        "mandatory_min_salary": True,
        "min_salary": 300000,
    }
    base.update(over)
    return base


def test_match_passes():
    ok, reason = prefilter(BY_ID["MOCK-1001"], _profile())
    assert ok is True, reason


def test_stop_word_rejected():
    ok, reason = prefilter(BY_ID["MOCK-1003"], _profile())
    assert ok is False and "стоп" in reason


def test_salary_gate_rejects_low_salary():
    ok, reason = prefilter(BY_ID["MOCK-1002"], _profile())
    assert ok is False and "зарплат" in reason


def test_off_target_title_rejected():
    ok, reason = prefilter(BY_ID["MOCK-1004"], _profile())
    assert ok is False and "должност" in reason


def test_required_keyword_missing():
    ok, reason = prefilter(BY_ID["MOCK-1001"], _profile(required_keywords=["python"]))
    assert ok is False and "обязательного" in reason
