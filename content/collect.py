#!/usr/bin/env python3
"""Считывание наполнения сайта + связь с Owner Agent API — источник для генерации контента.

Запускается в GitHub Actions (сеть GitHub не режет systemop.*), не в песочнице агента.

Пишет:
  content/site_content.md      — видимый текст страниц сайта (наполнение)
  content/platform_snapshot.json — БЕЗ клиентских данных: только факт связи с API и
                                   здоровье инфраструктуры (для факта «платформа онлайн»).

Только стандартная библиотека. Без ключа API часть с платформой пропускается.
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = os.environ.get("STAMP") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# пустая строка из GitHub (незаданная переменная) не должна перебивать дефолт → через `or`
SITES = [u.strip() for u in (os.environ.get("CONTENT_URLS")
         or "https://systemop.pro,https://systemop.top").split(",") if u.strip()]

API_BASE = os.environ.get("OWNER_AGENT_BASE", "https://systemop.pro/api/owner-agent")
API_KEY = os.environ.get("OWNER_AGENT_API_SECRET")

_SKIP = {"script", "style", "noscript", "svg", "head", "meta", "link"}
_BLOCK = {"p", "div", "section", "li", "h1", "h2", "h3", "h4", "br", "tr", "header", "footer"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            t = data.strip()
            if t:
                self.parts.append(t + " ")


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def static_text(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SystemOP content bot)"})
    html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    p = _Text()
    p.feed(html)
    return _clean("".join(p.parts))


def rendered_text(url: str, timeout: int = 35) -> str | None:
    """Рендер JS-сайта (SPA) через headless-браузер — иначе на systemop.* текста нет."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            pg = b.new_page(user_agent="Mozilla/5.0 (SystemOP content bot)")
            pg.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            pg.wait_for_timeout(1500)
            txt = pg.inner_text("body")
            b.close()
            return _clean(txt)
    except Exception as e:
        sys.stderr.write(f"[render] {url}: {type(e).__name__}: {str(e)[:120]}\n")
        return None


def page_text(url: str) -> str:
    """Сначала пробуем как настоящий браузер (SPA), при неудаче — статически."""
    txt = rendered_text(url)
    if txt and len(txt) > 40:
        return txt
    return static_text(url)


def collect_sites() -> str:
    out = [f"# Наполнение сайта (снимок {STAMP})\n"]
    for url in SITES:
        try:
            txt = page_text(url)
            out.append(f"\n## {url}\n\n{txt[:12000]}\n")
            print(f"  ✓ {url}: {len(txt)} символов")
        except Exception as e:
            out.append(f"\n## {url}\n\n(не удалось прочитать: {type(e).__name__}: {str(e)[:120]})\n")
            print(f"  ✗ {url}: {type(e).__name__}: {str(e)[:120]}")
    return "\n".join(out)


def api_snapshot() -> dict:
    """БЕЗ данных клиентов: только факт связи и здоровье инфраструктуры."""
    snap = {"api_ok": False, "checked": STAMP, "system": None}
    if not API_KEY:
        snap["note"] = "OWNER_AGENT_API_SECRET не задан — пропускаю платформу"
        return snap
    hdr = {"X-Owner-Agent-Key": API_KEY}
    try:
        req = urllib.request.Request(API_BASE + "/ping", headers=hdr)
        ping = json.load(urllib.request.urlopen(req, timeout=20))
        snap["api_ok"] = bool(ping.get("ok"))
    except Exception as e:
        snap["note"] = f"ping не прошёл: {type(e).__name__}: {str(e)[:120]}"
        return snap
    try:  # /system — здоровье инфраструктуры (без клиентских данных)
        req = urllib.request.Request(API_BASE + "/system", headers=hdr)
        snap["system"] = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:
        snap["note"] = f"system недоступен: {type(e).__name__}: {str(e)[:120]}"
    return snap


def api_help() -> str:
    """Каталог возможностей платформы из Owner Agent /help — реальные фичи для контента."""
    if not API_KEY:
        return ""
    try:
        req = urllib.request.Request(API_BASE + "/help", headers={"X-Owner-Agent-Key": API_KEY})
        data = json.load(urllib.request.urlopen(req, timeout=20))
        return json.dumps(data, ensure_ascii=False, indent=2)[:6000]
    except Exception as e:
        sys.stderr.write(f"[help] {type(e).__name__}: {str(e)[:120]}\n")
        return ""


def main():
    os.makedirs(HERE, exist_ok=True)
    site_md = collect_sites()
    helptxt = api_help()
    if helptxt:
        site_md += f"\n\n## Возможности платформы (Owner Agent /help)\n\n```json\n{helptxt}\n```\n"
        print(f"  ✓ каталог /help: {len(helptxt)} символов")
    with open(os.path.join(HERE, "site_content.md"), "w", encoding="utf-8") as f:
        f.write(site_md)
    snap = api_snapshot()
    with open(os.path.join(HERE, "platform_snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    print(f"API связь: {'✓' if snap['api_ok'] else '—'} | сайтов: {len(SITES)}")


if __name__ == "__main__":
    main()
