#!/usr/bin/env python3
"""Работа над ошибками: перед новым сценарием Claude заходит в панель (reels.json)
и учится на прошлых роликах — что заходило, что провалилось и какие ошибки из своих
же разборов не повторять.

digest(rtype) собирает компактную выжимку для промпта сценариста:
  • ТОП по времени досмотра (повторять приёмы),
  • худшие (не повторять),
  • частые ошибки и уже выписанные правки из reel["review"] (их пишет ig_review.py).

Источник — reels.json (та же панель). По умолчанию локальный файл; если задан
REELS_URL — тянет свежую версию по сети (у Mac есть интернет). Нет данных → "".
"""
from __future__ import annotations
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REELS_JSON = os.path.join(ROOT, "reels.json")


def _load(path: str | None = None):
    url = os.environ.get("REELS_URL")
    if url:
        try:
            import urllib.request
            return json.load(urllib.request.urlopen(url, timeout=15))
        except Exception:
            pass
    try:
        return json.load(open(path or REELS_JSON, encoding="utf-8"))
    except Exception:
        return None


def _watch_sec(r: dict) -> float:
    a = r.get("actual") or {}
    if a.get("avg_watch_s") is not None:
        return float(a["avg_watch_s"])
    if a.get("avg_watch_pct") is not None and r.get("duration"):
        return a["avg_watch_pct"] / 100.0 * r["duration"]
    return 0.0


def _uniq(xs, cap):
    seen, res = set(), []
    for x in xs:
        k = (x or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            res.append(x.strip())
        if len(res) >= cap:
            break
    return res


def _line(r: dict) -> str:
    a = r.get("actual") or {}
    bits = [f'«{(r.get("title") or "").strip()[:60]}»', f"{_watch_sec(r):.1f}с досм"]
    if a.get("views"):
        bits.append(f'{a["views"]} показов')
    if a.get("hook3s") is not None:
        bits.append(f'hook {a["hook3s"]}%')
    if a.get("completion") is not None:
        bits.append(f'до конца {a["completion"]}%')
    return " · ".join(bits)


def digest(rtype: str = "", path: str | None = None, max_lessons: int = 8) -> str:
    """Выжимка «работы над ошибками» из панели для промпта. "" — если данных нет."""
    doc = _load(path)
    if not doc:
        return ""
    reels = [r for r in (doc.get("reels") or []) if r.get("actual") and not r.get("sample")]
    if not reels:
        return ""
    ranked = sorted(reels, key=_watch_sec, reverse=True)
    top = ranked[:3]
    top_ids = {id(r) for r in top}
    worst = [r for r in reversed(ranked) if _watch_sec(r) > 0 and id(r) not in top_ids][:3]

    out = ["ЧТО ЗАХОДИЛО (повтори эти приёмы):"]
    out += [f"  + {_line(r)}" for r in top]
    if worst:                                  # худшие показываем только если это НЕ те же ролики
        out.append("ЧТО ПРОВАЛИЛОСЬ (не повторяй):")
        out += [f"  - {_line(r)}" for r in worst]

    # ошибки/правки из разборов Claude (приоритет — тот же формат)
    same = [r for r in reels if r.get("type") == rtype] if rtype else []
    pool = same or reels
    mistakes = _uniq([m for r in pool for m in ((r.get("review") or {}).get("mistakes") or [])],
                     max_lessons)
    fixes = _uniq([f for r in pool for f in ((r.get("review") or {}).get("fixes") or [])],
                  max_lessons)
    if mistakes:
        out.append("ЧАСТЫЕ ОШИБКИ ИЗ ТВОИХ РАЗБОРОВ (избегай):")
        out += [f"  • {m}" for m in mistakes]
    if fixes:
        out.append("ПРАВКИ, КОТОРЫЕ ТЫ УЖЕ ВЫПИСАЛ СЕБЕ (примени сейчас):")
        out += [f"  • {f}" for f in fixes]
    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Работа над ошибками из панели")
    ap.add_argument("--type", default="", help="ключ формата (product/expert/...)")
    a = ap.parse_args()
    d = digest(a.type)
    print(d or "нет данных в панели (reels.json пуст / нет опубликованных роликов)")
