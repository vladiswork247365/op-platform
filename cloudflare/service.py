#!/usr/bin/env python3
"""Cloudflare Containers — HTTP-триггер одного цикла рендера (stateless).

GET /run → rclone забирает инбокс «00 Исходники» → авто-рендер движком montage/
         → push в «01 Готовые» → отснятое переносится в архив (слив инбокса),
           чтобы следующий запуск не пересобирал то же самое.
GET /    → health-check.

Авторизация Google — через env-переменные rclone (секреты Cloudflare):
  RCLONE_CONFIG_GDRIVE_TYPE=drive
  RCLONE_CONFIG_GDRIVE_SCOPE=drive
  RCLONE_CONFIG_GDRIVE_TOKEN={"access_token":...,"refresh_token":...,...}
Папки — по ID: IN_ID / OUT_ID / ARCHIVE_ID (опц.).
"""
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MONTAGE = os.path.join(HERE, "montage")
DATA = os.environ.get("DATA", "/data")
REMOTE = os.environ.get("REMOTE", "gdrive")
IN_ID = os.environ.get("IN_ID")
OUT_ID = os.environ.get("OUT_ID")
ARCHIVE_ID = os.environ.get("ARCHIVE_ID")
MEDIA_EXT = ("mp4", "mov", "m4v", "jpg", "jpeg", "png", "heic", "heif", "webp")


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def cycle():
    if not (IN_ID and OUT_ID):
        return {"status": "misconfig", "err": "нужны env IN_ID и OUT_ID"}
    src = os.path.join(DATA, "sources")
    out = os.path.join(DATA, "out")
    os.makedirs(src, exist_ok=True)
    os.makedirs(out, exist_ok=True)

    sh(f'rclone copy "{REMOTE},root_folder_id={IN_ID}:" "{src}" --drive-acknowledge-abuse -q')
    media = [f for f in os.listdir(src) if f.rsplit(".", 1)[-1].lower() in MEDIA_EXT]
    if not media:
        return {"status": "empty"}

    p = subprocess.run([sys.executable, os.path.join(MONTAGE, "autorun.py"),
                        "--watch", src, "--out", out, "--once"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return {"status": "render_error", "err": p.stderr[-600:]}

    sh(f'rclone copy "{out}" "{REMOTE},root_folder_id={OUT_ID}:" -q')
    if ARCHIVE_ID:
        sh(f'rclone move "{REMOTE},root_folder_id={IN_ID}:" "{REMOTE},root_folder_id={ARCHIVE_ID}:" -q')
    for d in (src, out):
        for f in os.listdir(d):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    return {"status": "rendered", "sources": media, "at": time.strftime("%Y-%m-%d %H:%M:%S")}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/run"):
            try:
                self._send(200, cycle())
            except Exception as e:
                self._send(500, {"status": "error", "err": str(e)})
        else:
            self._send(200, {"ok": True, "service": "reels-factory"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"reels-factory service on :{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
