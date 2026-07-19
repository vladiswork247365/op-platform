#!/usr/bin/env python3
"""End-to-end DRY-RUN check + Deployment Report.

Runs the full pipeline against the mock source and mock AI in an isolated
temporary database, verifies every stage, and prints a PASS/FAIL report.
Exit code 0 only when the system is READY FOR PRODUCTION (no critical FAIL).

Usage:  python -m scripts.deploy_check
"""
from __future__ import annotations

import os
import sys
import tempfile

# Force a safe, isolated, offline configuration BEFORE importing the app.
_TMP = tempfile.mkdtemp(prefix="autopilot-e2e-")
os.environ.update(
    {
        "RUN_MODE": "dry_run",
        "DATABASE_URL": f"sqlite:///{_TMP}/e2e.db",
        "VACANCY_SOURCE": "mock",
        "AI_PROVIDER": "mock",
        "SCHEDULER_ENABLED": "false",
    }
)

# Make the package importable when run as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_db, session_scope  # noqa: E402
from app.health import self_diagnostic  # noqa: E402
from app.models import (  # noqa: E402
    AIAnalysis,
    Application,
    ApplyStatus,
    Contact,
    Decision,
    AppSetting,
    SystemRun,
    Vacancy,
    VacancyStatus,
    WhatsAppMessage,
)
from app.pipeline import run_cycle  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(stage: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((stage, ok, detail))


def seed_profile(db) -> None:
    AppSetting.set(db, "target_titles", ["Sales Manager", "менеджер по продажам"])
    AppSetting.set(db, "alt_titles", ["account manager"])
    AppSetting.set(db, "skills", ["CRM", "B2B", "продаж", "опыт"])
    AppSetting.set(db, "resume_text",
                   "Опыт продаж B2B, работа с CRM, ведение сделок, выполнение плана.")
    AppSetting.set(db, "min_salary", 300000)
    AppSetting.set(db, "mandatory_min_salary", True)
    AppSetting.set(db, "stop_words", ["сетевой", "MLM"])
    db.commit()


def main() -> int:
    # Stage: Backend + Database.
    try:
        init_db()
        check("Backend / imports", True)
        check("Database (migrations/init)", True)
    except Exception as exc:  # noqa: BLE001
        check("Database (migrations/init)", False, str(exc))
        return report()

    with session_scope() as db:
        seed_profile(db)

    # Stage: first cycle.
    with session_scope() as db:
        run = run_cycle(db)
        rid = run.id

    with session_scope() as db:
        run = db.get(SystemRun, rid)
        vacs = db.query(Vacancy).all()
        analyses = db.query(AIAnalysis).all()
        apps = db.query(Application).all()
        contacts = db.query(Contact).all()
        was = db.query(WhatsAppMessage).all()

        check("Vacancy source (search)", run.found >= 5, f"found={run.found}")
        check("Vacancy persisted", len(vacs) >= 4, f"stored={len(vacs)}")
        check("Deduplication (in-run)", run.duplicates >= 1, f"dupes={run.duplicates}")
        check("Prefilter", run.rejected >= 2, f"rejected={run.rejected}")
        filtered = [v for v in vacs if v.status == VacancyStatus.FILTERED_OUT.value]
        check("Filter drops off-target", len(filtered) >= 2, f"filtered={len(filtered)}")
        check("AI analysis", len(analyses) >= 1, f"analyses={len(analyses)}")
        matched = [v for v in vacs if v.decision == Decision.MATCH.value]
        check("Match score / decision", run.matched >= 1 and len(matched) >= 1,
              f"matched={run.matched}")
        top = max((a.score for a in analyses), default=0)
        check("Score computed", top >= 85, f"top_score={top}")

        dry_apps = [a for a in apps if a.status == ApplyStatus.DRY_RUN.value]
        check("Cover letter built", all(len(a.cover_letter) > 10 for a in dry_apps) and dry_apps,
              f"cover_apps={len(dry_apps)}")
        check("Application pre-check (DRY_RUN, nothing sent)",
              len(dry_apps) >= 1 and not any(v.applied for v in vacs),
              f"dry_run_apps={len(dry_apps)}, real_applied={sum(v.applied for v in vacs)}")
        check("Contact extraction", len(contacts) >= 1, f"contacts={len(contacts)}")
        check("WhatsApp pre-check", len(was) >= 1,
              f"wa={len(was)} status={was[0].status if was else '-'}")
        check("Logging / audit", run.detail == "ok", f"run.detail={run.detail}")

    # Stage: second cycle proves cross-run dedup (no new, no new applications).
    with session_scope() as db:
        run2 = run_cycle(db)
        check("Deduplication (cross-run)", run2.new == 0 and run2.applied == 0,
              f"new={run2.new} applied={run2.applied}")

    # Stage: health / self-diagnostic.
    with session_scope() as db:
        rep = self_diagnostic(db)
        check("Health / self-diagnostic", rep["status"] != "ERROR",
              f"status={rep['status']}")
        check("Dashboard data (summary)", rep.get("queue_depth", -1) >= 0)

    return report()


def report() -> int:
    print("\n" + "=" * 58)
    print("  SYSTEM DEPLOYMENT — END-TO-END DRY RUN REPORT")
    print("=" * 58)
    critical_fail = False
    for stage, ok, detail in RESULTS:
        tag = "PASS" if ok else "FAIL"
        if not ok:
            critical_fail = True
        line = f"  {stage:<42} {tag}"
        if detail:
            line += f"  ({detail})"
        print(line)
    print("-" * 58)
    print("  WhatsApp: NOT CONFIGURED (by design)")
    print("=" * 58)
    if critical_fail:
        print("  OVERALL: NOT READY FOR PRODUCTION")
        print("=" * 58)
        return 1
    print("  OVERALL: READY FOR PRODUCTION (dry-run verified)")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
