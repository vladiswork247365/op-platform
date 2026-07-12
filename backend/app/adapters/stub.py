"""Заглушка-адаптер: гоняет весь конвейер зелёным без реального инструмента.

submit() эмулирует async: спустя секунду сам стучится в POST /webhook/tool
(как это делал бы реальный инструмент), отдавая на выход исходное сырьё.
Так вся труба — включая callback-путь — проверяется до подключения реального рендера.
# REPLACE PER TOOL
"""
from __future__ import annotations

import threading

import httpx

from ..config import settings


class StubAdapter:
    name = "stub"

    def submit(self, job, settings_snapshot: dict) -> str:
        external_id = f"stub-{job.id}"
        payload = {
            "external_job_id": external_id,
            "status": "succeeded",
            # «отрендеренный» выход = то самое сырьё, залитое в R2 на шаге downloading
            "output_url": job.source_stored_url,
            "cost": 0.01,
        }
        # эмуляция async-вебхука инструмента через 1 сек
        threading.Timer(1.0, _fire_callback, args=(payload,)).start()
        return external_id

    def parse_callback(self, payload: dict) -> dict:
        return {
            "external_job_id": payload.get("external_job_id"),
            "status": payload.get("status", "succeeded"),
            "output_url": payload.get("output_url"),
            "cost": float(payload.get("cost") or 0),
            "error": payload.get("error"),
        }


def _fire_callback(payload: dict) -> None:
    try:
        httpx.post(f"{settings.PANEL_BASE_URL.rstrip('/')}/webhook/tool", json=payload, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"[stub] callback failed: {e}")


ADAPTER = StubAdapter()
