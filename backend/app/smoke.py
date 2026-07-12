"""End-to-end прогон на заглушке: создаём job через /webhook/telegram и ждём done.

Требует поднятых API (:8000) и воркера. Токен/R2 не нужны — работает dev-фолбэк.
"""
from __future__ import annotations

import sys
import time

import httpx

from .config import settings

BASE = settings.PANEL_BASE_URL.rstrip("/")

FAKE_UPDATE = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "chat": {"id": 123456789, "type": "private"},
        "caption": "reels",  # ключевое слово = имя сид-пресета
        "video": {"file_id": "SMOKE_TEST_FILE_ID", "duration": 5},
    },
}


def main() -> int:
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{BASE}/webhook/telegram", json=FAKE_UPDATE)
        r.raise_for_status()
        data = r.json()
        job_id = data.get("job_id")
        if not job_id:
            print("FAIL: job не создан:", data)
            return 1
        print("job создан:", job_id)

        deadline = time.time() + 90
        last = None
        while time.time() < deadline:
            j = c.get(f"{BASE}/api/jobs/{job_id}").json()
            state = (j["status"], j.get("stage"))
            if state != last:
                print(f"  {j['status']}/{j.get('stage')}")
                last = state
            if j["status"] == "done":
                print("✅ DONE")
                print("   master :", j["master_url"])
                print("   preview:", j["preview_url"])
                print("   cost   :", j["cost"])
                return 0
            if j["status"] == "error":
                print("❌ ERROR:", j["error_text"])
                return 1
            time.sleep(1)
    print("FAIL: таймаут ожидания done")
    return 1


if __name__ == "__main__":
    sys.exit(main())
