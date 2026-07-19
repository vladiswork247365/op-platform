from app.dedup import content_hash, is_known, normalize
from app.models import Vacancy
from app.sources.mock import CATALOG


def test_content_hash_ignores_whitespace_and_case():
    a = CATALOG[0]
    b = type(a)(**{**a.__dict__})
    b.title = a.title.upper() + "   "
    b.description = "  " + a.description.replace(" ", "  ")
    assert content_hash(a) == content_hash(b)


def test_normalize():
    assert normalize("  Hello   World ") == "hello world"


def test_is_known_by_external_id(db):
    rv = CATALOG[0]
    ch = content_hash(rv)
    assert is_known(db, "mock", rv.external_id, ch) is False
    db.add(Vacancy(source="mock", external_id=rv.external_id, content_hash=ch,
                   title=rv.title, company=rv.company))
    db.commit()
    assert is_known(db, "mock", rv.external_id, ch) is True


def test_is_known_by_content_hash_new_id(db):
    rv = CATALOG[0]
    ch = content_hash(rv)
    db.add(Vacancy(source="mock", external_id="OTHER-ID", content_hash=ch,
                   title=rv.title, company=rv.company))
    db.commit()
    # Same content, different external id -> still recognised as duplicate.
    assert is_known(db, "mock", "BRAND-NEW-ID", ch) is True
