#!/usr/bin/env python3
"""
Достаёт «виральные углы» (angles) из данных платформы АСП.

Источники (в корне репозитория):
  - live.json     — живые баллы: stats + authors[{name, points, msgs, cats, act{d,w,m}}]
  - profiles.json — карточки участников: {slug: {phone, niche, role, company, what, ...}}

Углы — это готовые идеи роликов с реальными числами, чтобы сценарий
не выдумывался «из воздуха», а строился на фактах рейтинга.

Использование:
    python3 .claude/skills/viral-video/scripts/angles.py            # все углы
    python3 .claude/skills/viral-video/scripts/angles.py --json      # машиночитаемо
    python3 .claude/skills/viral-video/scripts/angles.py --top 5     # размер топов
"""
import json
import os
import sys
import argparse

def _find_root():
    """Идём вверх от файла скрипта, пока не встретим live.json (корень репо)."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.exists(os.path.join(d, "live.json")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    # запасной вариант — текущая рабочая директория
    return os.getcwd()


ROOT = _find_root()


def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def norm(a):
    """Нормализуем автора: гарантируем cats/act."""
    a.setdefault("cats", {})
    a.setdefault("act", {})
    for k in ("d", "w", "m"):
        a["act"].setdefault(k, 0)
    a.setdefault("points", 0)
    a.setdefault("msgs", 0)
    return a


def build_angles(top=5):
    live = load("live.json")
    authors = [norm(dict(a)) for a in live.get("authors", []) if a.get("name")]
    stats = live.get("stats", {})

    def top_by(key, label, extractor):
        ranked = sorted(authors, key=extractor, reverse=True)[:top]
        return {
            "id": key,
            "label": label,
            "members": [
                {
                    "name": m["name"],
                    "points": m["points"],
                    "week": m["act"]["w"],
                    "month": m["act"]["m"],
                    "expert": m["cats"].get("экспертный", 0),
                    "cases": m["cats"].get("кейс", 0),
                    "questions": m["cats"].get("вопрос", 0),
                }
                for m in ranked
            ],
        }

    angles = []

    # 1. Топ недели — кто больше всех активничал за 7 дней
    angles.append(top_by("top_week", "Топ недели по активности", lambda m: m["act"]["w"]))

    # 2. Эксперты — кто даёт больше всего экспертных сообщений
    angles.append(top_by("experts", "Эксперты сообщества", lambda m: m["cats"].get("экспертный", 0)))

    # 3. Кейсы — кто делится реальными кейсами
    angles.append(top_by("cases", "Разбор кейсов", lambda m: m["cats"].get("кейс", 0)))

    # 4. Ворвались — высокая недельная активность при небольшом общем счёте
    #    (недельные баллы велики относительно total → «новая волна»)
    def momentum(m):
        return m["act"]["w"] / (m["points"] + 50.0)
    risers = sorted([m for m in authors if m["act"]["w"] >= 20], key=momentum, reverse=True)[:top]
    angles.append({
        "id": "risers",
        "label": "Ворвались в рейтинг (моментум недели)",
        "members": [
            {"name": m["name"], "points": m["points"], "week": m["act"]["w"],
             "momentum": round(momentum(m), 3)}
            for m in risers
        ],
    })

    return {"stats": stats, "updatedAt": live.get("updatedAt"), "angles": angles}


def enrich_with_profile(name):
    """Пытаемся найти карточку участника по имени (нестрого)."""
    try:
        profiles = load("profiles.json")
    except Exception:
        return None
    key = "".join(ch for ch in name.lower() if ch.isalnum())
    for slug, p in profiles.items():
        if key and (key in slug or slug in key):
            return {"slug": slug, **{k: p.get(k) for k in ("niche", "role", "company", "what")}}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    data = build_angles(top=args.top)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return

    s = data["stats"]
    print(f"📊 АСП · обновлено {data['updatedAt']}")
    print(f"   участников: {s.get('members')} · сообщений: {s.get('msgs')} "
          f"· полезных: {s.get('useful')} · экспертных: {s.get('expert')} · кейсов: {s.get('cases')}")
    print()
    for ang in data["angles"]:
        print(f"🎬 [{ang['id']}] {ang['label']}")
        for i, m in enumerate(ang["members"], 1):
            extra = " · ".join(
                f"{k}={v}" for k, v in m.items() if k != "name" and v
            )
            print(f"   {i}. {m['name']:<28} {extra}")
        print()


if __name__ == "__main__":
    main()
