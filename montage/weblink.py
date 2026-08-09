#!/usr/bin/env python3
"""Ссылка-референс к ТЗ: тянем контент по URL (заголовок, описание, текст) как ориентир.

Автор кидает в бота ссылку (на референс-ролик, статью, лендинг) вместе с ТЗ —
система читает страницу и передаёт сценаристу как «целься в такой результат».
Для соцсетей берём og:title/og:description (там обычно подпись/хук). Только stdlib.
"""
from __future__ import annotations
import re
import urllib.request
from html.parser import HTMLParser

UA = "Mozilla/5.0 (ViralMaking bot)"
URL_RE = re.compile(r"https?://[^\s]+")


class _P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self.meta, self.parts = "", {}, []
        self._skip, self._intitle = 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:title", "og:description", "description",
                       "twitter:title", "twitter:description") and a.get("content"):
                self.meta.setdefault(key, a["content"])
        if tag == "title":
            self._intitle = True
        if tag in ("script", "style", "noscript", "svg", "head"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._intitle = False
        if tag in ("script", "style", "noscript", "svg", "head") and self._skip:
            self._skip -= 1

    def handle_data(self, d):
        if self._intitle:
            self.title += d
        elif not self._skip:
            t = d.strip()
            if t:
                self.parts.append(t)


def find_url(text: str) -> str | None:
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(").,;!?") if m else None


def fetch(url: str, timeout: int = 20, max_chars: int = 2500) -> str:
    """Достать текст-референс по ссылке. "" — если не открылось."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except Exception:
        return ""
    p = _P()
    try:
        p.feed(html)
    except Exception:
        pass
    title = (p.meta.get("og:title") or p.meta.get("twitter:title") or p.title or "").strip()
    desc = (p.meta.get("og:description") or p.meta.get("description")
            or p.meta.get("twitter:description") or "").strip()
    body = re.sub(r"\s+", " ", " ".join(p.parts)).strip()
    out = []
    if title:
        out.append("Заголовок: " + title)
    if desc:
        out.append("Описание/подпись: " + desc)
    if body and len(body) > len(desc) + 20:
        out.append("Текст страницы: " + body[:1500])
    return ("\n".join(out))[:max_chars]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Референс по ссылке")
    ap.add_argument("url")
    a = ap.parse_args()
    print(fetch(a.url) or "не удалось прочитать ссылку")
