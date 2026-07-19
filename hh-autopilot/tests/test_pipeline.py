from app.models import (
    AIAnalysis,
    Application,
    ApplyStatus,
    Contact,
    Decision,
    Vacancy,
    VacancyStatus,
)
from app.pipeline import run_cycle
from tests.conftest import configure_profile


def test_full_cycle_dry_run(db):
    configure_profile(db)
    run = run_cycle(db)

    assert run.found == 5
    assert run.new == 4            # 1005 is a content duplicate of 1001
    assert run.duplicates == 1
    assert run.matched == 1        # only 1001 matches
    assert run.rejected >= 2       # 1002/1003/1004 dropped by prefilter
    assert run.applied == 1        # dry-run application recorded
    assert run.errors == 0

    # Nothing was really sent in dry-run.
    assert not any(v.applied for v in db.query(Vacancy).all())
    app = db.query(Application).first()
    assert app.status == ApplyStatus.DRY_RUN.value
    assert len(app.cover_letter) > 10

    # A match produced analysis + contact.
    assert db.query(AIAnalysis).count() == 1
    assert db.query(Contact).count() == 1

    matched = db.query(Vacancy).filter(Vacancy.decision == Decision.MATCH.value).all()
    assert len(matched) == 1 and matched[0].external_id == "MOCK-1001"


def test_cross_run_deduplication(db):
    configure_profile(db)
    run_cycle(db)
    run2 = run_cycle(db)
    assert run2.new == 0
    assert run2.applied == 0
    assert run2.duplicates == 5


def test_review_queue_populated(db):
    # Lower profile specificity so the match lands in REVIEW instead of MATCH.
    configure_profile(db)
    from app.models import AppSetting

    # Raise the auto-apply threshold above the achievable score.
    AppSetting.set(db, "auto_apply_min_score", 99)
    AppSetting.set(db, "review_min_score", 50)
    db.commit()
    run = run_cycle(db)
    assert run.review >= 1
    attention = (
        db.query(Vacancy)
        .filter(Vacancy.status == VacancyStatus.NEEDS_ATTENTION.value)
        .all()
    )
    assert len(attention) >= 1
