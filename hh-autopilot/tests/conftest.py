"""Shared pytest fixtures: an isolated in-file SQLite DB per test session."""
from __future__ import annotations

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="autopilot-tests-")
os.environ.setdefault("RUN_MODE", "dry_run")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP}/test.db")
os.environ.setdefault("VACANCY_SOURCE", "mock")
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base, AppSetting  # noqa: E402


@pytest.fixture()
def db():
    # Fresh schema for each test for full isolation.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    AppSetting.ensure_defaults(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


def configure_profile(db):
    """A profile under which MOCK-1001 is a strong MATCH."""
    AppSetting.set(db, "target_titles", ["Sales Manager", "менеджер по продажам"])
    AppSetting.set(db, "skills", ["CRM", "B2B", "продаж", "опыт"])
    AppSetting.set(db, "resume_text",
                   "Опыт продаж B2B, работа с CRM, ведение сделок, выполнение плана.")
    AppSetting.set(db, "min_salary", 300000)
    AppSetting.set(db, "mandatory_min_salary", True)
    AppSetting.set(db, "stop_words", ["сетевой", "MLM"])
    db.commit()
