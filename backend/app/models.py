"""Ядро данных: presets (то, что правит юзер) и jobs (одна строка = один ролик).

Машина статусов job = отслеживание изменений. Отдельной таблицы логов нет.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# --- допустимые значения статус-машины (держим рядом с моделью) ---
STATUSES = ("accepted", "processing", "done", "error", "canceled")
STAGES = ("downloading", "rendering", "assembling", "delivering")


class Preset(Base):
    """Рецепт: что и как собрать. Правится пользователем, но не ломает историю
    (job хранит замороженную копию в settings_snapshot)."""

    __tablename__ = "presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)               # ключевое слово команды
    tool: Mapped[str] = mapped_column(Text, nullable=False)              # trendy/heygen/higgsfield/elevenlabs
    format: Mapped[str] = mapped_column(Text, default="9:16")            # 9:16 / 16:9 / 1:1
    voice: Mapped[str | None] = mapped_column(Text, default=None)         # id голоса
    subtitle_style: Mapped[dict] = mapped_column(JSONB, default=dict)     # {font,color,position,...}
    prompt: Mapped[str | None] = mapped_column(Text, default=None)        # промпт/закадр
    length: Mapped[int | None] = mapped_column(Integer, default=None)     # целевая длина, сек
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)              # доп. параметры инструмента

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    jobs: Mapped[list["Job"]] = relationship(back_populates="preset")

    def as_snapshot(self) -> dict:
        """Замороженная копия пресета на момент создания job."""
        return {
            "preset_id": self.id,
            "name": self.name,
            "tool": self.tool,
            "format": self.format,
            "voice": self.voice,
            "subtitle_style": self.subtitle_style or {},
            "prompt": self.prompt,
            "length": self.length,
            "extra": self.extra or {},
        }


class Job(Base):
    """Один ролик = цепочка статусов. Вся динамика системы — тут."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preset_id: Mapped[int] = mapped_column(ForeignKey("presets.id"), nullable=False)

    source_ref: Mapped[str] = mapped_column(Text, nullable=False)         # telegram file_id или URL сырья
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)      # куда вернуть результат

    status: Mapped[str] = mapped_column(String(16), default="accepted", nullable=False)
    stage: Mapped[str | None] = mapped_column(String(16), default=None)

    settings_snapshot: Mapped[dict | None] = mapped_column(JSONB, default=None)
    external_job_id: Mapped[str | None] = mapped_column(Text, default=None)  # id задачи в инструменте

    # --- рабочие поля async-конвейера (расширение сверх ТЗ, см. README) ---
    source_stored_url: Mapped[str | None] = mapped_column(Text, default=None)  # сырьё, залитое в R2
    tool_output_url: Mapped[str | None] = mapped_column(Text, default=None)    # выход инструмента до FFmpeg

    master_url: Mapped[str | None] = mapped_column(Text, default=None)
    preview_url: Mapped[str | None] = mapped_column(Text, default=None)
    cost: Mapped[float | None] = mapped_column(Numeric(12, 4), default=None)
    error_text: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    preset: Mapped["Preset"] = relationship(back_populates="jobs")
