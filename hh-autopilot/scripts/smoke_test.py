#!/usr/bin/env python3
"""Smoke test: the app boots, /health is green and key pages/APIs respond."""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="autopilot-smoke-")
os.environ.update(
    {
        "RUN_MODE": "dry_run",
        "DATABASE_URL": f"sqlite:///{_TMP}/smoke.db",
        "VACANCY_SOURCE": "mock",
        "AI_PROVIDER": "mock",
        "SCHEDULER_ENABLED": "false",
    }
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main() -> int:
    failures = 0
    with TestClient(app) as client:
        for path in ["/health", "/api/summary", "/api/vacancies", "/", "/vacancies",
                     "/attention", "/settings", "/runs"]:
            r = client.get(path)
            ok = r.status_code == 200
            print(f"  GET {path:<20} -> {r.status_code} {'OK' if ok else 'FAIL'}")
            failures += 0 if ok else 1
        health = client.get("/health").json()
        print(f"  health.status = {health['status']}")
        if health["status"] == "ERROR":
            failures += 1
    print("SMOKE TEST:", "PASS" if failures == 0 else f"FAIL ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
