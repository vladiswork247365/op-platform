"""APScheduler-based autopilot scheduler with error isolation + self-healing.

Jobs:
  * cycle      — the autopilot search/analyse/apply cycle (configurable interval)
  * retries    — process due retry tasks with backoff (every 5 min)
  * diagnostic — daily extended self-check
  * watchdog   — re-arms missing jobs / records job crashes (self-healing)

A crash inside any job is caught, logged and isolated: it never stops the
scheduler or the other jobs. Process-level crashes are handled by the Docker
restart policy.
"""
from __future__ import annotations

import logging

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .audit import audit, log_error
from .config import Settings, get_settings
from .db import session_scope
from .health import self_diagnostic
from .pipeline import process_retries, run_cycle
from .runtime import effective_interval_hours

log = logging.getLogger("autopilot.scheduler")

CYCLE_JOB = "autopilot_cycle"
RETRY_JOB = "autopilot_retries"
DIAG_JOB = "autopilot_diagnostic"
WATCHDOG_JOB = "autopilot_watchdog"


def _guard(fn, component: str):
    """Wrap a job so an exception is logged, not propagated."""

    def wrapper():
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", component)
            try:
                with session_scope() as db:
                    log_error(db, component, str(exc))
            except Exception:  # noqa: BLE001 — logging must never crash the job
                log.exception("failed to persist error for %s", component)

    return wrapper


def _cycle_job():
    with session_scope() as db:
        run_cycle(db)


def _retry_job():
    with session_scope() as db:
        process_retries(db)


def _diagnostic_job():
    with session_scope() as db:
        report = self_diagnostic(db, scheduler=MANAGER.scheduler)
        audit(db, "self_diagnostic", f"healthy={report.get('healthy')}")
        if not report.get("healthy"):
            log_error(
                db,
                "self_diagnostic",
                f"system not healthy: status={report.get('status')} "
                f"stuck_tasks={report.get('stuck_tasks')}",
            )


class SchedulerManager:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.scheduler: BackgroundScheduler | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self) -> None:
        if self.scheduler and self.scheduler.running:
            return
        self.scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600}
        )
        self.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self._arm_jobs()
        self.scheduler.start()
        log.info("scheduler started")

    def _arm_jobs(self) -> None:
        assert self.scheduler is not None
        with session_scope() as db:
            hours = effective_interval_hours(db, self.settings)
        self.scheduler.add_job(
            _guard(_cycle_job, "cycle"),
            IntervalTrigger(hours=hours),
            id=CYCLE_JOB,
            replace_existing=True,
        )
        self.scheduler.add_job(
            _guard(_retry_job, "retries"),
            IntervalTrigger(minutes=5),
            id=RETRY_JOB,
            replace_existing=True,
        )
        self.scheduler.add_job(
            _guard(_diagnostic_job, "diagnostic"),
            CronTrigger(hour=self.settings.self_diagnostic_hour, minute=0),
            id=DIAG_JOB,
            replace_existing=True,
        )
        self.scheduler.add_job(
            _guard(self._watchdog, "watchdog"),
            IntervalTrigger(minutes=10),
            id=WATCHDOG_JOB,
            replace_existing=True,
        )

    def reschedule(self, hours: float) -> None:
        """Change the cycle interval live (called from the panel)."""
        if not self.scheduler:
            return
        self.scheduler.reschedule_job(CYCLE_JOB, trigger=IntervalTrigger(hours=hours))
        log.info("cycle rescheduled to every %s h", hours)

    def run_cycle_now(self) -> None:
        if self.scheduler:
            self.scheduler.add_job(_guard(_cycle_job, "cycle"), id="cycle_now",
                                   replace_existing=True)

    def shutdown(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            log.info("scheduler stopped")

    # ── self-healing ───────────────────────────────────────────────────────
    def _on_job_error(self, event) -> None:
        with session_scope() as db:
            log_error(db, "scheduler", f"job {event.job_id} raised: {event.exception}")

    def _watchdog(self) -> None:
        """Re-arm any missing job and restart the scheduler if it died."""
        if not self.scheduler or not self.scheduler.running:
            log.warning("watchdog: scheduler not running — restarting")
            self.start()
            return
        existing = {j.id for j in self.scheduler.get_jobs()}
        required = {CYCLE_JOB, RETRY_JOB, DIAG_JOB}
        if not required.issubset(existing):
            log.warning("watchdog: missing jobs %s — re-arming", required - existing)
            self._arm_jobs()


# Module-level singleton used by the app and health checks.
MANAGER = SchedulerManager()
