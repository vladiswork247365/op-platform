"""Effective runtime settings: panel overrides (AppSetting) fall back to env."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .config import Settings
from .models import AppSetting


def effective_run_mode(db: Session, settings: Settings) -> str:
    override = AppSetting.get_raw(db, "run_mode")
    return override if override in ("dry_run", "production") else settings.run_mode


def is_production(db: Session, settings: Settings) -> bool:
    return effective_run_mode(db, settings) == "production"


def effective_interval_hours(db: Session, settings: Settings) -> float:
    v = AppSetting.get_raw(db, "search_interval_hours")
    try:
        return float(v) if v else settings.search_interval_hours
    except (TypeError, ValueError):
        return settings.search_interval_hours


def effective_thresholds(db: Session, settings: Settings) -> tuple[int, int]:
    auto = AppSetting.get_raw(db, "auto_apply_min_score")
    review = AppSetting.get_raw(db, "review_min_score")
    auto = int(auto) if auto not in (None, "") else settings.auto_apply_min_score
    review = int(review) if review not in (None, "") else settings.review_min_score
    return auto, review


def load_profile(db: Session) -> dict:
    """The candidate + search + cover-letter profile as a plain dict."""
    return AppSetting.all_as_dict(db)


def search_params(profile: dict) -> dict:
    return {
        "search_text": profile.get("search_text", ""),
        "search_area": profile.get("search_area", ""),
        "search_experience": profile.get("search_experience", ""),
        "search_employment": profile.get("search_employment", ""),
        "search_schedule": profile.get("search_schedule", ""),
        "search_salary": profile.get("search_salary"),
        "per_page": profile.get("search_per_page", 20),
    }
