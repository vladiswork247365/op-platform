#!/usr/bin/env python3
"""Разбор роликов через ~6 часов после публикации — прямо в панель (reels.json).

Берёт метрики из reels.json (их туда кладёт ig_stats.py из Instagram API), и для
каждого ролика, которому уже ≥6ч и у которого ещё нет разбора, просит Claude
(feedback.py) дать развёрнутую обратную связь по ошибкам. Результат пишет в
reel["review"] — панель reels.html показывает его в карточке ролика.

Запускается в GitHub Actions по расписанию (montage автосбор), но можно и локально:
  python3 montage/ig_review.py --write            # разобрать 6ч+ ролики без разбора
  python3 montage/ig_review.py --write --force     # перепроверить все заново
  python3 montage/ig_review.py --min-age-hours 6   # порог возраста (по умолчанию 6)

Без OPENROUTER_API_KEY — тихо выходит (0), чтобы не ронять пайплайн.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REELS_JSON = os.path.join(ROOT, "reels.json")

sys.path.insert(0, HERE)
import feedback  # noqa: E402  — мозг разбора (метрики → ошибки/правки)


def load_env():
    for path in (os.path.join(HERE, ".env"), os.path.join(ROOT, ".env")):
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _published_dt(actual: dict):
    """Момент публикации из actual.published_at (ISO) или actual.published (дата)."""
    ts = actual.get("published_at") or actual.get("published")
    if not ts:
        return None
    ts = str(ts).replace("Z", "+00:00")
    if len(ts) == 10:            # только дата → начало суток
        ts += "T00:00:00+00:00"
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _age_hours(actual: dict):
    dt = _published_dt(actual)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _metrics_text(reel: dict) -> str:
    """Собрать метрики ролика в текст для аналитика (с контекстом: заголовок/цель)."""
    a = reel.get("actual") or {}
    lines = [f"Заголовок/хук ролика: {reel.get('title', '—')}"]
    if reel.get("goal"):
        lines.append(f"Цель ролика: {reel['goal']}")
    if reel.get("duration"):
        lines.append(f"Длительность: {reel['duration']}с")
    est = " (оценка)" if a.get("estimated") else ""
    pairs = [
        ("Показы/просмотры", a.get("views")),
        ("Hook 3с, %", (f"{a['hook3s']}{est}" if a.get("hook3s") is not None else None)),
        ("Средний досмотр, %", (f"{a['avg_watch_pct']}{est}" if a.get("avg_watch_pct") is not None else None)),
        ("Среднее время досмотра, сек", a.get("avg_watch_s")),
        ("Досмотр до конца, %", (f"{a['completion']}{est}" if a.get("completion") is not None else None)),
        ("Сохранения", a.get("saves")),
        ("Репосты", a.get("shares")),
        ("Лайки", a.get("likes")),
        ("Комментарии", a.get("comments")),
        ("Дата публикации", a.get("published")),
    ]
    for name, val in pairs:
        if val is not None:
            lines.append(f"{name}: {val}")
    if a.get("curve"):
        lines.append("Кривая удержания (оценка, %): " + ", ".join(str(x) for x in a["curve"]))
    return "\n".join(lines)


def review_reels(min_age_hours: float = 6.0, force: bool = False, limit: int = 0,
                 write: bool = False, stamp: str = "") -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY не задан — пропускаю разбор (это не ошибка).")
        return 0
    if not os.path.exists(REELS_JSON):
        print("нет reels.json — нечего разбирать.")
        return 0
    doc = json.load(open(REELS_JSON, encoding="utf-8"))
    reels = doc.get("reels") or []
    done = skipped = 0
    for reel in reels:
        if reel.get("sample"):                       # образцы не разбираем
            continue
        a = reel.get("actual")
        if not a:
            continue
        if reel.get("review") and not force:
            continue
        age = _age_hours(a)
        if age is None or age < min_age_hours:
            skipped += 1
            continue
        rtype = reel.get("type") or ""               # если бот проставил формат
        rv = feedback.analyze_text(_metrics_text(reel), script=reel.get("script"), rtype=rtype)
        if not rv:
            print(f"  ✗ {reel.get('id')}: разбор не получился (сеть/ключ?)")
            continue
        rv["generated_at"] = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rv["age_hours"] = round(age, 1)
        reel["review"] = rv
        done += 1
        print(f"  ✓ {reel.get('id')}: разбор готов (score {rv.get('score', '?')}/10, {age:.0f}ч)")
        if limit and done >= limit:
            break
    print(f"\nразобрано: {done} · ждут 6ч: {skipped}")
    if write and done:
        doc["updatedAt"] = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        json.dump(doc, open(REELS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("✅ reels.json обновлён (разборы вписаны).")
    elif done:
        print("(dry-run — добавь --write, чтобы записать разборы в reels.json)")
    return done


def main():
    load_env()
    ap = argparse.ArgumentParser(description="Разбор Reels через 6ч → в панель")
    ap.add_argument("--min-age-hours", type=float, default=6.0)
    ap.add_argument("--force", action="store_true", help="перепроверить все заново")
    ap.add_argument("--limit", type=int, default=0, help="максимум разборов за прогон")
    ap.add_argument("--write", action="store_true", help="записать в reels.json")
    ap.add_argument("--stamp", default="", help="метка времени (RFC3339)")
    a = ap.parse_args()
    review_reels(a.min_age_hours, a.force, a.limit, a.write, a.stamp)


if __name__ == "__main__":
    main()
