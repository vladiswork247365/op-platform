"""Подключение к Postgres. Синхронный SQLAlchemy 2.0 — проще для воркера и Alembic."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
