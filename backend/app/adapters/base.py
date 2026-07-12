"""Общий контракт адаптера. # REPLACE PER TOOL — по одному модулю на инструмент."""
from __future__ import annotations

from typing import Protocol


class Adapter(Protocol):
    name: str

    def submit(self, job, settings: dict) -> str:
        """Отправляет задачу в инструмент (async submit). Возвращает external_job_id."""
        ...

    def parse_callback(self, payload: dict) -> dict:
        """Разбирает вебхук инструмента.

        Возвращает {"output_url": str, "cost": float, "status": "succeeded"|"failed",
                     "external_job_id": str, "error": str|None}.
        """
        ...
