"""The core orchestration: one autopilot cycle end-to-end.

  source.search → dedup → prefilter → AI analysis → scoring/decision →
  cover letter → apply pre-check → apply (or dry-run) → contacts →
  WhatsApp prepare → persist → per-run stats + audit.

Every vacancy is processed inside its own try/except so a single bad item can
never abort the cycle. The retry worker reuses `perform_apply`.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .ai import build_ai
from .ai.base import AnalysisContext
from .apply import perform_apply
from .audit import audit, log_error
from .config import Settings, get_settings
from .contacts import extract_and_save
from .cover_letter import build as build_cover
from .dedup import content_hash, is_known
from .models import (
    AIAnalysis,
    ApplyStatus,
    Contact,
    Decision,
    SystemRun,
    Vacancy,
    VacancyStatus,
    utcnow,
)
from .prefilter import prefilter
from .retry import due_tasks, mark_done, schedule_next
from .runtime import (
    effective_thresholds,
    is_production,
    load_profile,
    search_params,
)
from .scoring import decide
from .sources import build_source
from .sources.base import RawVacancy


def _to_ctx(rv: RawVacancy, profile: dict) -> AnalysisContext:
    return AnalysisContext(
        title=rv.title,
        company=rv.company,
        description=rv.description,
        area=rv.area,
        salary_from=rv.salary_from,
        salary_to=rv.salary_to,
        schedule=rv.schedule,
        experience=rv.experience,
        employment=rv.employment,
        resume_text=profile.get("resume_text", ""),
        target_titles=profile.get("target_titles", []),
        alt_titles=profile.get("alt_titles", []),
        skills=profile.get("skills", []),
        remote_ok=bool(profile.get("remote_ok", True)),
        min_salary=int(profile.get("min_salary") or 0),
        stop_words=profile.get("stop_words", []),
    )


def _persist_vacancy(db: Session, source_name: str, rv: RawVacancy, chash: str) -> Vacancy:
    v = Vacancy(
        source=source_name,
        external_id=rv.external_id,
        url=rv.url,
        title=rv.title,
        company=rv.company,
        area=rv.area,
        salary_from=rv.salary_from,
        salary_to=rv.salary_to,
        salary_currency=rv.salary_currency,
        schedule=rv.schedule,
        experience=rv.experience,
        employment=rv.employment,
        description=rv.description,
        content_hash=chash,
        published_at=rv.published_at,
        discovered_at=utcnow(),
        status=VacancyStatus.NEW.value,
        raw_json=json.dumps(rv.raw, ensure_ascii=False, default=str)[:100000],
    )
    db.add(v)
    db.flush()
    return v


def run_cycle(db: Session, settings: Settings | None = None) -> SystemRun:
    settings = settings or get_settings()
    profile = load_profile(db)
    source = build_source(settings)
    ai = build_ai(settings)
    auto_min, review_min = effective_thresholds(db, settings)
    production = is_production(db, settings)

    run = SystemRun(source=source.name, started_at=utcnow())
    db.add(run)
    db.flush()
    audit(db, "cycle.start", f"mode={'production' if production else 'dry_run'}")
    db.commit()

    try:
        found = source.search(search_params(profile))
    except Exception as exc:  # noqa: BLE001
        run.errors += 1
        run.ok = False
        run.detail = f"source.search failed: {exc}"
        run.finished_at = utcnow()
        log_error(db, "source", str(exc))
        db.commit()
        return run

    run.found = len(found)
    db.commit()
    applied_this_cycle = 0

    def process_item(item: RawVacancy, applied_so_far: int) -> int:
        """Process one vacancy. Returns 1 if an application was made/simulated.

        Soft rejections return 0 and are committed by the caller; unexpected
        errors raise and are rolled back per-item so one bad vacancy cannot
        abort the cycle.
        """
        chash = content_hash(item)
        if is_known(db, source.name, item.external_id, chash):
            run.duplicates += 1
            return 0
        run.new += 1

        # Fetch full detail (description + contacts) when possible.
        rv = item
        try:
            rv = source.fetch_detail(item.external_id)
            chash = content_hash(rv)
        except Exception:  # noqa: BLE001 — fall back to list data
            rv = item

        vacancy = _persist_vacancy(db, source.name, rv, chash)

        # Cheap prefilter (before spending an AI call).
        passed, reason = prefilter(rv, profile)
        if not passed:
            vacancy.status = VacancyStatus.FILTERED_OUT.value
            vacancy.decision = Decision.REJECT.value
            run.rejected += 1
            audit(db, "prefilter.reject", reason, vacancy.id)
            return 0

        # AI analysis.
        run.sent_to_ai += 1
        try:
            result = ai.analyze(_to_ctx(rv, profile))
        except Exception as exc:  # noqa: BLE001 — handled, not fatal
            vacancy.status = VacancyStatus.NEEDS_ATTENTION.value
            vacancy.attention_reason = f"AI error: {exc}"
            log_error(db, "ai", str(exc))
            run.errors += 1
            return 0

        analysis_row = AIAnalysis(
            vacancy_id=vacancy.id,
            decision="",
            score=result.score,
            experience_match=result.experience_match,
            skills_match=result.skills_match,
            title_match=result.title_match,
            salary_match=result.salary_match,
            format_match=result.format_match,
            reasons=json.dumps(result.reasons, ensure_ascii=False),
            risks=json.dumps(result.risks, ensure_ascii=False),
            provider=result.provider,
        )
        db.add(analysis_row)
        db.flush()
        vacancy.score = result.score

        decision, dreason = decide(rv, result, profile, auto_min, review_min)
        vacancy.decision = decision.value
        analysis_row.decision = decision.value
        vacancy.status = VacancyStatus.ANALYZED.value

        if decision is Decision.REJECT:
            run.rejected += 1
            vacancy.status = VacancyStatus.SKIPPED.value
            audit(db, "decision.reject", dreason, vacancy.id)
            return 0
        if decision is Decision.REVIEW:
            run.review += 1
            vacancy.status = VacancyStatus.NEEDS_ATTENTION.value
            vacancy.attention_reason = f"REVIEW: {dreason} (score={result.score})"
            audit(db, "decision.review", dreason, vacancy.id)
            return 0

        # MATCH.
        run.matched += 1

        # Contacts (only officially published) + WhatsApp prepare (stub).
        contact = extract_and_save(db, vacancy, rv)
        from .whatsapp import prepare as wa_prepare

        wa_prepare(db, vacancy, contact, profile.get("whatsapp_template", ""))

        # Safety cap on applications per cycle.
        if applied_so_far >= settings.per_cycle_apply_limit:
            vacancy.status = VacancyStatus.NEEDS_ATTENTION.value
            vacancy.attention_reason = "достигнут лимит откликов за цикл"
            audit(db, "apply.cap", "per-cycle limit reached", vacancy.id)
            return 0

        cover = build_cover(rv, profile, ai)
        status = perform_apply(db, settings, source, vacancy, cover, production)
        if status in (ApplyStatus.APPLIED.value, ApplyStatus.DRY_RUN.value):
            run.applied += 1
            return 1
        return 0

    for item in found:
        try:
            applied_this_cycle += process_item(item, applied_this_cycle)
            db.commit()
        except Exception as exc:  # noqa: BLE001 — never let one item kill the run
            db.rollback()
            run.errors += 1
            log_error(db, "pipeline", f"item {item.external_id}: {exc}")
            db.commit()

    run.finished_at = utcnow()
    run.ok = run.errors == 0
    run.detail = "ok" if run.ok else f"{run.errors} error(s)"
    audit(
        db,
        "cycle.finish",
        f"new={run.new} match={run.matched} review={run.review} "
        f"reject={run.rejected} applied={run.applied} errors={run.errors}",
    )
    db.commit()
    return run


def process_retries(db: Session, settings: Settings | None = None) -> int:
    """Run due retry tasks. Returns how many were processed."""
    settings = settings or get_settings()
    source = build_source(settings)
    production = is_production(db, settings)
    tasks = due_tasks(db)
    processed = 0
    for task in tasks:
        processed += 1
        if task.kind != "apply" or task.vacancy_id is None:
            mark_done(db, task)
            continue
        vacancy = db.get(Vacancy, task.vacancy_id)
        if vacancy is None:
            mark_done(db, task)
            continue
        app = vacancy.application
        cover = app.cover_letter if app else ""
        try:
            perform_apply(
                db, settings, source, vacancy, cover, production, retry_task=task
            )
        except Exception as exc:  # noqa: BLE001
            schedule_next(db, task, str(exc), settings.max_retries)
            log_error(db, "retry", str(exc))
    return processed
