"""SQLAlchemy ORM models — the full data model of the system.

Entities (per the spec):
  Vacancy, CandidateProfile, Resume, SearchProfile, AIAnalysis, Application,
  Contact, WhatsAppMessage, SystemRun, ErrorLog, AuditLog, RetryTask.
Plus AppSetting: a key/value store for panel-editable runtime settings.
"""
from __future__ import annotations

import enum
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Enums / string constants ───────────────────────────────────────────────
class Decision(str, enum.Enum):
    MATCH = "MATCH"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class VacancyStatus(str, enum.Enum):
    NEW = "NEW"
    FILTERED_OUT = "FILTERED_OUT"      # rejected by cheap prefilter
    ANALYZED = "ANALYZED"
    APPLIED = "APPLIED"
    APPLY_FAILED = "APPLY_FAILED"
    APPLY_PENDING = "APPLY_PENDING"     # queued for retry
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    SKIPPED = "SKIPPED"                  # dry-run / below threshold / duplicate


class ApplyStatus(str, enum.Enum):
    APPLIED = "APPLIED"
    APPLY_FAILED = "APPLY_FAILED"
    DRY_RUN = "DRY_RUN"
    SKIPPED = "SKIPPED"


class WhatsAppStatus(str, enum.Enum):
    WHATSAPP_SENT = "WHATSAPP_SENT"
    WHATSAPP_FAILED = "WHATSAPP_FAILED"
    WHATSAPP_NOT_AVAILABLE = "WHATSAPP_NOT_AVAILABLE"
    WHATSAPP_SKIPPED = "WHATSAPP_SKIPPED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class RetryStatus(str, enum.Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


# ── Core entities ──────────────────────────────────────────────────────────
class Vacancy(Base):
    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), default="headhunter", index=True)
    external_id: Mapped[str] = mapped_column(String(120), index=True)
    url: Mapped[str] = mapped_column(String(500), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    company: Mapped[str] = mapped_column(String(300), default="")
    area: Mapped[str] = mapped_column(String(120), default="")
    salary_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(10), default="")
    schedule: Mapped[str] = mapped_column(String(60), default="")
    experience: Mapped[str] = mapped_column(String(60), default="")
    employment: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # dedup hash of company + title + normalized description
    content_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    status: Mapped[str] = mapped_column(String(30), default=VacancyStatus.NEW.value, index=True)
    decision: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    whatsapp_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    attention_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    raw_json: Mapped[str] = mapped_column(Text, default="{}")

    analysis = relationship("AIAnalysis", back_populates="vacancy", uselist=False)
    application = relationship("Application", back_populates="vacancy", uselist=False)
    contact = relationship("Contact", back_populates="vacancy", uselist=False)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_source_external"),
    )


class AIAnalysis(Base):
    __tablename__ = "ai_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id"), index=True)
    decision: Mapped[str] = mapped_column(String(10))
    score: Mapped[int] = mapped_column(Integer)
    experience_match: Mapped[int] = mapped_column(Integer, default=0)
    skills_match: Mapped[int] = mapped_column(Integer, default=0)
    title_match: Mapped[int] = mapped_column(Integer, default=0)
    salary_match: Mapped[int] = mapped_column(Integer, default=0)
    format_match: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[str] = mapped_column(Text, default="[]")   # JSON list
    risks: Mapped[str] = mapped_column(Text, default="[]")     # JSON list
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vacancy = relationship("Vacancy", back_populates="analysis")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    cover_letter: Mapped[str] = mapped_column(Text, default="")
    # idempotency key prevents duplicate applications on retry / worker restart
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider_operation_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    provider_response: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vacancy = relationship("Vacancy", back_populates="application")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    messenger: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vacancy = relationship("Vacancy", back_populates="contact")


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id"), index=True)
    phone: Mapped[str] = mapped_column(String(60), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default=WhatsAppStatus.NOT_CONFIGURED.value)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SystemRun(Base):
    __tablename__ = "system_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="")
    found: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    sent_to_ai: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    review: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    applied: Mapped[int] = mapped_column(Integer, default=0)
    whatsapp: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class ErrorLog(Base):
    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    component: Mapped[str] = mapped_column(String(60), default="", index=True)
    kind: Mapped[str] = mapped_column(String(60), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    permanent: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    vacancy_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class RetryTask(Base):
    __tablename__ = "retry_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)     # e.g. "apply"
    vacancy_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(20), default=RetryStatus.PENDING.value, index=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppSetting(Base):
    """Key/value store for panel-editable runtime settings (JSON values)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="null")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    # Default runtime settings. These mirror config defaults but can be edited
    # live from the panel without restart.
    DEFAULTS: dict[str, Any] = {
        "run_mode": None,                # None -> fall back to env RUN_MODE
        "search_interval_hours": None,
        "auto_apply_min_score": None,
        "review_min_score": None,
        # Candidate profile
        "resume_text": "",
        "target_titles": [],
        "alt_titles": [],
        "skills": [],
        "cities": [],
        "remote_ok": True,
        "min_salary": 0,
        "stop_words": [],
        "required_keywords": [],
        "mandatory_min_salary": False,   # hard gate overriding score
        # Search profile (HH query params)
        "search_text": "sales manager",
        "search_area": "40",             # 40 = Kazakhstan
        "search_experience": "",
        "search_employment": "",
        "search_schedule": "",
        "search_salary": None,
        "search_per_page": 20,
        # Cover letter
        "cover_letter_mode": "static",   # "static" | "ai"
        "cover_letter_text": "Здравствуйте! Меня заинтересовала ваша вакансия. "
        "Мой опыт соответствует требованиям, буду рад обсудить детали.",
        "whatsapp_template": "",
    }

    @classmethod
    def ensure_defaults(cls, db) -> None:
        existing = {s.key for s in db.query(cls).all()}
        for key, val in cls.DEFAULTS.items():
            if key not in existing:
                db.add(cls(key=key, value=json.dumps(val)))
        db.flush()

    @classmethod
    def get(cls, db, key: str, default: Any = None) -> Any:
        row = db.get(cls, key)
        if row is None:
            return cls.DEFAULTS.get(key, default)
        try:
            v = json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            return default
        return v if v is not None else (cls.DEFAULTS.get(key, default))

    @classmethod
    def get_raw(cls, db, key: str, default: Any = None) -> Any:
        """Like get() but returns None if the stored value is JSON null."""
        row = db.get(cls, key)
        if row is None:
            return default
        try:
            return json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            return default

    @classmethod
    def set(cls, db, key: str, value: Any) -> None:
        row = db.get(cls, key)
        if row is None:
            row = cls(key=key, value=json.dumps(value))
            db.add(row)
        else:
            row.value = json.dumps(value)
        db.flush()

    @classmethod
    def all_as_dict(cls, db) -> dict[str, Any]:
        out = dict(cls.DEFAULTS)
        for row in db.query(cls).all():
            try:
                out[row.key] = json.loads(row.value)
            except (json.JSONDecodeError, TypeError):
                pass
        return out
