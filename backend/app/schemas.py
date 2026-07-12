"""Pydantic-схемы API (вход/выход ручек)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------- Presets ----------
class PresetBase(BaseModel):
    name: str
    tool: str = "stub"
    format: str = "9:16"
    voice: str | None = None
    subtitle_style: dict = Field(default_factory=dict)
    prompt: str | None = None
    length: int | None = None
    extra: dict = Field(default_factory=dict)


class PresetCreate(PresetBase):
    pass


class PresetUpdate(BaseModel):
    name: str | None = None
    tool: str | None = None
    format: str | None = None
    voice: str | None = None
    subtitle_style: dict | None = None
    prompt: str | None = None
    length: int | None = None
    extra: dict | None = None


class PresetOut(PresetBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


# ---------- Jobs ----------
class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    preset_id: int
    source_ref: str
    chat_id: int
    status: str
    stage: str | None
    settings_snapshot: dict | None
    external_job_id: str | None
    master_url: str | None
    preview_url: str | None
    cost: float | None
    error_text: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class JobList(BaseModel):
    total: int
    items: list[JobOut]
