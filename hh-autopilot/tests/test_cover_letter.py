from app.cover_letter import build, final_check
from app.sources.mock import CATALOG

RV = CATALOG[0]


def test_static_build_returns_base_text():
    profile = {"cover_letter_mode": "static", "cover_letter_text": "Здравствуйте, готов обсудить."}
    assert build(RV, profile) == "Здравствуйте, готов обсудить."


def test_final_check_rejects_empty():
    ok, reason = final_check("", RV)
    assert ok is False and "пуст" in reason


def test_final_check_rejects_template_vars():
    ok, reason = final_check("Здравствуйте, {{company}}, меня заинтересовала вакансия!", RV)
    assert ok is False and "переменные" in reason


def test_final_check_passes_valid():
    ok, reason = final_check("Здравствуйте! Мой опыт продаж соответствует вакансии.", RV)
    assert ok is True and reason == ""
