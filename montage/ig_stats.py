#!/usr/bin/env python3
"""Сбор статистики Reels из Instagram Graph API → в reels.json (формат панели).

Что тянется АВТОМАТОМ из API: показы/охват (views/reach), среднее время досмотра
(ig_reels_avg_watch_time), сохранения, репосты, лайки, комментарии, дата.

Чего в Graph API НЕТ (Meta не отдаёт — видно только в приложении, в графике
удержания): hook 3с, % досмотра до конца, кривая удержания. Их коллектор
ОЦЕНИВАЕТ из среднего досмотра (флаг estimated=true) — пока не впишешь точные
цифры со скрина Insights; ручные значения оценка не перетирает.

Нужны переменные окружения (в montage/.env или корневом .env, chmod 600):
  IG_USER_ID      — id бизнес/креатор-аккаунта Instagram (см. montage/IG-SETUP.md)
  IG_ACCESS_TOKEN — долгоживущий токен с правами instagram_manage_insights
  IG_API_VERSION  — опц., по умолчанию v21.0
  IG_APP_ID / IG_APP_SECRET — опц., только для --refresh-token

Примеры:
  python3 montage/ig_stats.py --whoami          # проверить токен и аккаунт
  python3 montage/ig_stats.py --limit 10        # показать статы (dry-run)
  python3 montage/ig_stats.py --limit 25 --write  # записать в reels.json
  python3 montage/ig_stats.py --refresh-token   # продлить токен на ~60 дней
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REELS_JSON = os.path.join(ROOT, "reels.json")
# Два режима авторизации:
#   instagram (по умолчанию) — «Instagram API с входом через Instagram»: без
#     Facebook-страницы и бизнес-портфолио; хост graph.instagram.com, аккаунт = me.
#   facebook — классика через Facebook-страницу (IG_USER_ID + fb_exchange_token).
# Переключается переменной IG_AUTH=facebook при необходимости.
AUTH = os.environ.get("IG_AUTH", "instagram").lower()
IG_LOGIN = not AUTH.startswith("f")
API_VERSION = os.environ.get("IG_API_VERSION", "v21.0")
GRAPH = "https://graph.instagram.com" if IG_LOGIN else "https://graph.facebook.com"

# метрики media-insights для Reels; недоступные в текущей версии API молча отсеются
REEL_METRICS = ["views", "reach", "saved", "shares", "likes", "comments",
                "total_interactions", "ig_reels_avg_watch_time",
                "ig_reels_video_view_total_time", "clips_replays_count", "plays"]


# ── .env ────────────────────────────────────────────────────────────────────
def load_env():
    for path in (os.path.join(ROOT, "montage", ".env"), os.path.join(ROOT, ".env"),
                 os.path.join(ROOT, "studio", ".env")):
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


# ── HTTP ──────────────────────────────────────────────────────────────────────
def api_get(path, params):
    # graph.instagram.com работает без версии в пути; у facebook — с версией
    prefix = f"{GRAPH}" if IG_LOGIN else f"{GRAPH}/{API_VERSION}"
    url = f"{prefix}/{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=45) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
            msg = body.get("error", {}).get("message", str(e))
        except Exception:
            msg = f"HTTP {e.code}"
        return None, msg
    except Exception as e:
        return None, str(e)


def need(var):
    v = os.environ.get(var)
    if not v:
        sys.exit(f"❌ Нет {var}. Впиши в montage/.env — как получить: montage/IG-SETUP.md")
    return v


# ── оценка кривой удержания из среднего досмотра ──────────────────────────────
def estimate_curve(avg_pct, duration_s=None, points=5):
    """Из среднего % досмотра строим убывающую кривую (start=100), mean≈avg_pct.
    Возвращает (curve[], completion, hook3s|None). Всё помечается estimated."""
    if not avg_pct or avg_pct <= 0:
        return None, None, None
    target = min(max(avg_pct / 100.0, 0.02), 0.99)
    fr = [i / (points - 1) for i in range(points)]

    def mean_for(k):
        return sum(math.exp(-k * f) for f in fr) / points

    lo, hi = 0.0, 12.0
    for _ in range(60):  # бисекция по коэффициенту спада
        mid = (lo + hi) / 2
        (lo, hi) = (mid, hi) if mean_for(mid) > target else (lo, mid)
    k = (lo + hi) / 2
    curve = [round(100 * math.exp(-k * f)) for f in fr]
    curve[0] = 100
    completion = curve[-1]
    hook3s = None
    if duration_s and duration_s > 0:
        hook3s = round(100 * math.exp(-k * (3.0 / duration_s)))
    return curve, completion, hook3s


# ── сбор ──────────────────────────────────────────────────────────────────────
def fetch_insights(media_id, token):
    """Тянет метрики; при ошибке по неподдерживаемой метрике — добирает поштучно."""
    data, err = api_get(f"{media_id}/insights",
                        {"metric": ",".join(REEL_METRICS), "access_token": token})
    out = {}
    if data and "data" in data:
        for m in data["data"]:
            vals = m.get("values") or [{}]
            out[m["name"]] = vals[0].get("value")
        return out
    # fallback: по одной метрике, несовместимые пропускаем
    for metric in REEL_METRICS:
        d, e = api_get(f"{media_id}/insights",
                      {"metric": metric, "access_token": token})
        if d and d.get("data"):
            out[metric] = (d["data"][0].get("values") or [{}])[0].get("value")
    return out


def to_actual(node, ins, duration_s=None):
    def g(*keys):
        for k in keys:
            if ins.get(k) is not None:
                return ins[k]
        return None
    views = g("views", "plays", "reach")
    avg_ms = g("ig_reels_avg_watch_time")
    avg_pct = None
    if avg_ms and duration_s:
        avg_pct = round(min(avg_ms / 1000.0 / duration_s * 100, 100))
    curve, completion, hook3s = estimate_curve(avg_pct, duration_s)
    actual = {
        "views": views,
        "hook3s": hook3s,
        "avg_watch_pct": avg_pct,
        "completion": completion,
        "curve": curve,
        "saves": g("saved"),
        "shares": g("shares"),
        "likes": g("likes") if g("likes") is not None else node.get("like_count"),
        "comments": g("comments") if g("comments") is not None else node.get("comments_count"),
        "source": "instagram",
        "published": (node.get("timestamp") or "")[:10],
        "permalink": node.get("permalink"),
        "avg_watch_s": round(avg_ms / 1000.0, 1) if avg_ms else None,
        "estimated": bool(avg_pct),  # кривая/хук/completion оценены, не из API
    }
    return actual


def fetch_reels(limit, token, ig_user):
    fields = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"
    data, err = api_get(f"{ig_user}/media",
                       {"fields": fields, "limit": limit, "access_token": token})
    if err:
        sys.exit(f"❌ Ошибка API media: {err}")
    reels = []
    for node in data.get("data", []):
        if node.get("media_product_type") not in ("REELS", "CLIPS") and \
           node.get("media_type") not in ("VIDEO",):
            continue
        reels.append(node)
    return reels


# ── запись в reels.json ───────────────────────────────────────────────────────
def shortcode(permalink):
    if not permalink:
        return None
    parts = [p for p in permalink.split("/") if p]
    return parts[-1] if parts else None


def merge_into_reels(fetched, stamp):
    doc = json.load(open(REELS_JSON, encoding="utf-8"))
    reels = doc.setdefault("reels", [])
    by_link = {}
    for r in reels:
        pl = (r.get("source") or {}).get("permalink") or (r.get("actual") or {}).get("permalink")
        if pl:
            by_link[pl.rstrip("/")] = r
    added = updated = 0
    for node, actual in fetched:
        pl = (actual.get("permalink") or "").rstrip("/")
        dur = None
        target = by_link.get(pl)
        if target:
            dur = target.get("duration")
            prev = target.get("actual") or {}
            # ручные (не estimated) значения кривой/хука/completion — не трогаем
            if prev and not prev.get("estimated"):
                for k in ("hook3s", "completion", "curve", "avg_watch_pct"):
                    if prev.get(k) is not None:
                        actual[k] = prev[k]
                actual["estimated"] = False
            target["actual"] = actual
            target["status"] = "scored"
            updated += 1
        else:
            cap = (node.get("caption") or "").strip().splitlines()
            title = (cap[0] if cap else "Reel").strip()[:80] or "Reel"
            reels.append({
                "id": f"ig_{shortcode(pl) or len(reels)+1}",
                "title": title,
                "status": "scored",
                "sample": False,
                "platform": "reels",
                "source": {"permalink": pl, "desc": "Импорт из Instagram"},
                "actual": actual,
            })
            added += 1
    doc["updatedAt"] = stamp
    json.dump(doc, open(REELS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return added, updated


# ── вывод ─────────────────────────────────────────────────────────────────────
def print_table(fetched):
    print(f"\n{'дата':10} {'views':>8} {'ср.досм':>8} {'до конца':>9} {'сохр':>6} "
          f"{'репост':>6} {'лайк':>6}  заголовок")
    print("─" * 92)
    for node, a in fetched:
        est = "~" if a.get("estimated") else " "
        title = (node.get("caption") or "").strip().splitlines()
        title = (title[0] if title else "")[:34]
        awp = f"{a['avg_watch_pct']}%{est}" if a.get("avg_watch_pct") else "—"
        comp = f"{a['completion']}%{est}" if a.get("completion") else "—"
        print(f"{a['published'] or '—':10} {str(a['views'] or '—'):>8} {awp:>8} {comp:>9} "
              f"{str(a['saves'] or '—'):>6} {str(a['shares'] or '—'):>6} {str(a['likes'] or '—'):>6}  {title}")
    print("\n  ~ = оценка (кривая/досмотр из среднего; точные — со скрина Insights).")


def cmd_refresh_token():
    tok = need("IG_ACCESS_TOKEN")
    if IG_LOGIN:
        # instagram-login: продление без app id/secret
        data, err = api_get("refresh_access_token",
                           {"grant_type": "ig_refresh_token", "access_token": tok})
    else:
        app_id, secret = need("IG_APP_ID"), need("IG_APP_SECRET")
        data, err = api_get("oauth/access_token", {
            "grant_type": "fb_exchange_token", "client_id": app_id,
            "client_secret": secret, "fb_exchange_token": tok})
    if err:
        sys.exit(f"❌ Не удалось продлить токен: {err}")
    new = data.get("access_token", "")
    ttl = data.get("expires_in")
    print("✅ Новый долгоживущий токен получен"
          + (f" (живёт ~{int(ttl)//86400} дн.)" if ttl else ""))
    print("   Впиши в montage/.env:  IG_ACCESS_TOKEN=" + new[:12] + "…(полностью из вывода ниже)")
    print("\nIG_ACCESS_TOKEN=" + new)


def main():
    load_env()
    ap = argparse.ArgumentParser(description="Сбор статистики Reels из Instagram Graph API")
    ap.add_argument("--limit", type=int, default=25, help="сколько последних постов взять")
    ap.add_argument("--write", action="store_true", help="записать в reels.json")
    ap.add_argument("--whoami", action="store_true", help="проверить токен и аккаунт")
    ap.add_argument("--refresh-token", action="store_true", help="продлить токен (~60 дн.)")
    ap.add_argument("--stamp", default="", help="метка времени для updatedAt (RFC3339)")
    a = ap.parse_args()

    if a.refresh_token:
        return cmd_refresh_token()

    token = need("IG_ACCESS_TOKEN")
    # в instagram-login режиме id не нужен — аккаунт это "me"
    ig_user = "me" if IG_LOGIN else need("IG_USER_ID")

    if a.whoami:
        fields = "user_id,username,account_type" if IG_LOGIN else "username,followers_count,media_count"
        data, err = api_get(ig_user, {"fields": fields, "access_token": token})
        if err:
            sys.exit(f"❌ Токен не принят: {err}")
        extra = (f" · {data.get('account_type')}" if IG_LOGIN
                 else f" · подписчиков {data.get('followers_count')} · постов {data.get('media_count')}")
        print(f"✅ Аккаунт: @{data.get('username')}{extra}")
        return

    nodes = fetch_reels(a.limit, token, ig_user)
    if not nodes:
        print("Постов-видео/Reels не найдено (или у токена нет прав insights).")
        return
    fetched = [(n, to_actual(n, fetch_insights(n["id"], token))) for n in nodes]
    print_table(fetched)

    if a.write:
        stamp = a.stamp or ((fetched[0][1].get("published") or "") + "T00:00:00Z")
        added, updated = merge_into_reels(fetched, stamp)
        print(f"\n✅ reels.json обновлён: +{added} новых, {updated} обновлено.")
    else:
        print("\n(dry-run — добавь --write, чтобы записать в reels.json)")


if __name__ == "__main__":
    main()
