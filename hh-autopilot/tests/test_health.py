from app.health import ONLINE, build_health, self_diagnostic
from app.pipeline import run_cycle
from tests.conftest import configure_profile


def test_health_reports_components(db):
    report = build_health(db, scheduler=None)
    assert report["components"]["database"]["status"] == ONLINE
    assert "vacancy_source" in report["components"]
    assert report["queue_depth"] >= 0
    assert report["errors_24h"] >= 0


def test_last_successful_cycle_tracked(db):
    configure_profile(db)
    run_cycle(db)
    report = build_health(db, scheduler=None)
    assert report["last_successful_cycle"] is not None


def test_self_diagnostic_healthy(db):
    configure_profile(db)
    run_cycle(db)
    rep = self_diagnostic(db)
    assert rep["status"] != "ERROR"
    assert rep["stuck_tasks"] == 0
    assert rep["healthy"] is True
    assert "disk_free_mb" in rep
