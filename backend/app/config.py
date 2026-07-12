"""Конфигурация панели. Все секреты — только здесь, во фронт не уходят никогда."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Postgres ---
    DATABASE_URL: str = "postgresql+psycopg2://panel:panel@localhost:5432/panel"

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = ""
    # Секрет из setWebhook (X-Telegram-Bot-Api-Secret-Token). Пусто = проверку не делаем.
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # --- Cloudflare R2 (S3-совместимое) ---
    R2_ACCOUNT_ID: str = "fcba16d0818bd4d4a36e81093c2e043b"
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = "systemaop-files"
    # Публичный базовый URL бакета (если раздаётся через public/custom domain).
    R2_PUBLIC_BASE_URL: str = ""

    # --- Выбранный видео-инструмент ---
    TOOL: str = "stub"  # trendy / heygen / higgsfield / elevenlabs / stub
    TOOL_API_KEY: str = ""

    # --- Публичный URL самой панели (для вебхуков инструмента и т.п.) ---
    PANEL_BASE_URL: str = "http://127.0.0.1:8000"

    # --- Локальное хранилище-фолбэк, когда R2-креды не заданы ---
    LOCAL_STORAGE_DIR: str = "./_storage"

    # --- FFmpeg (assembling + dev-генерация сырья) ---
    FFMPEG_BIN: str = "ffmpeg"

    # --- Dev-режим: если у Telegram нет токена, сырьё генерируется ffmpeg-ом ---
    # чтобы можно было прогнать конвейер зелёным без реального бота.
    DEV_FAKE_SOURCE: bool = True

    @property
    def r2_enabled(self) -> bool:
        return bool(self.R2_ACCESS_KEY_ID and self.R2_SECRET_ACCESS_KEY)

    @property
    def r2_endpoint(self) -> str:
        return f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


settings = Settings()
