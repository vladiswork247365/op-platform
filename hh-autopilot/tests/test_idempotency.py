from app.apply import perform_apply
from app.config import get_settings
from app.models import Application, ApplyStatus, Vacancy, VacancyStatus
from app.retry import apply_idempotency_key
from app.sources.mock import MockSource

COVER = "Здравствуйте! Мой опыт продаж соответствует вакансии, готов обсудить."


def _vacancy(db):
    v = Vacancy(source="mock", external_id="MOCK-1001", title="Sales Manager",
                company="Acme", status=VacancyStatus.ANALYZED.value)
    db.add(v)
    db.commit()
    return v


def test_apply_is_idempotent_in_production(db):
    settings = get_settings()
    src = MockSource()
    v = _vacancy(db)

    s1 = perform_apply(db, settings, src, v, COVER, is_production=True)
    db.commit()
    assert s1 == ApplyStatus.APPLIED.value
    assert v.applied is True

    # Second call must NOT create a second application nor re-send.
    s2 = perform_apply(db, settings, src, v, COVER, is_production=True)
    db.commit()
    assert s2 == ApplyStatus.APPLIED.value
    assert db.query(Application).filter(Application.vacancy_id == v.id).count() == 1


def test_dry_run_then_production_applies_once(db):
    settings = get_settings()
    src = MockSource()
    v = _vacancy(db)

    assert perform_apply(db, settings, src, v, COVER, is_production=False) == ApplyStatus.DRY_RUN.value
    db.commit()
    assert v.applied is False
    assert db.query(Application).count() == 1

    assert perform_apply(db, settings, src, v, COVER, is_production=True) == ApplyStatus.APPLIED.value
    db.commit()
    assert v.applied is True
    # Still a single application row, keyed by idempotency key.
    key = apply_idempotency_key(v.id)
    apps = db.query(Application).filter(Application.idempotency_key == key).all()
    assert len(apps) == 1 and apps[0].status == ApplyStatus.APPLIED.value


def test_empty_cover_letter_blocks_send(db):
    settings = get_settings()
    src = MockSource()
    v = _vacancy(db)
    status = perform_apply(db, settings, src, v, "  ", is_production=True)
    db.commit()
    assert status == ApplyStatus.SKIPPED.value
    assert v.status == VacancyStatus.NEEDS_ATTENTION.value
    assert v.applied is False
