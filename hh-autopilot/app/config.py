"""Application configuration loaded from environment / .env.

All secrets and tunables live here. Nothing sensitive is hard-coded in the
codebase — API keys are read from the environment only.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── Runtime mode ───────────────────────────────────────────────────────
    # DRY_RUN never sends applications / messages. It is the safe default and
    # must be explicitly turned off (RUN_MODE=production) after the E2E test.
    run_mode: Literal["dry_run", "production"] = "dry_run"

    # ── Storage ────────────────────────────────────────────────────────────
    # SQLite by default (zero infra). Override with a Postgres URL if desired.
    database_url: str = "sqlite:///./data/autopilot.db"

    # ── Vacancy source ─────────────────────────────────────────────────────
    # "headhunter" for the real api.hh.ru adapter, "mock" for offline/dry-run.
    vacancy_source: Literal["headhunter", "mock"] = "mock"
    hh_api_base: str = "https://api.hh.ru"
    hh_user_agent: str = "hh-autopilot/1.0 (contact@example.com)"
    # OAuth2 access token — required only to send applications (negotiations).
    hh_access_token: str = ""
    hh_resume_id: str = ""

    # ── AI provider ────────────────────────────────────────────────────────
    # "anthropic" for real analysis, "mock" for deterministic offline scoring.
    ai_provider: Literal["anthropic", "mock"] = "mock"
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5"
    ai_max_tokens: int = 1024

    # ── Scheduler ──────────────────────────────────────────────────────────
    scheduler_enabled: bool = True
    search_interval_hours: float = 2.0  # editable from the panel
    self_diagnostic_hour: int = 3       # daily extended system check (local hour)

    # ── Scoring thresholds (editable from the panel) ───────────────────────
    auto_apply_min_score: int = 85   # >= -> auto apply
    review_min_score: int = 65       # >= review, < auto_apply -> REVIEW queue
    # below review_min_score -> REJECT

    # ── Retry / safety ─────────────────────────────────────────────────────
    max_retries: int = 4
    per_cycle_apply_limit: int = 25  # safety cap: max applications per cycle

    # ── Web ────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def is_production(self) -> bool:
        return self.run_mode == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
