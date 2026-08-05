#!/usr/bin/env python3
"""Авто-обработчик Reels-фабрики.

Следит за папкой исходников (например, синхронизированной «00 Исходники» из
Google Drive для компьютера) и при появлении новых файлов сам строит EDL и
рендерит вертикальный ролик в папку выхода («01 Готовые»).

Запускается ТАМ, ГДЕ ЕСТЬ ФАЙЛЫ:
  • на Mac/ПК с «Google Drive для компьютера» — папки Диска локальны, авторизация
    уже сделана самим Google Drive, ничего дополнительно настраивать не надо;
  • на сервере — рядом положи rclone-синк папок Диска (см. README).

Пример:
  python3 montage/autorun.py \
      --watch "~/Google Drive/.../00 Исходники (съёмки)" \
      --out   "~/Google Drive/.../01 Готовые ролики"

Залил ролик с телефона → Drive синхронизировал в папку → обработчик собрал
черновой динамичный reel → он появился в «01 Готовые» → синхронизировался обратно
на телефон. «Залил — и всё».
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import auto_edl

HERE = os.path.dirname(os.path.abspath(__file__))


def snapshot(folder):
    items = []
    for f in sorted(os.listdir(folder)):
        p = os.path.join(folder, f)
        if os.path.isfile(p) and not f.startswith(".") and not f.startswith("_auto"):
            items.append((f, os.path.getsize(p)))
    return hashlib.md5(str(items).encode()).hexdigest(), items


def has_media(items):
    return any(os.path.splitext(f)[1].lower() in (auto_edl.VIDEO_EXT | auto_edl.IMAGE_EXT)
               for f, _ in items)


def process(watch, out, fps):
    edl = auto_edl.build_edl(watch, fps=fps)
    plan = os.path.join(watch, "_auto.edl.json")
    with open(plan, "w", encoding="utf-8") as f:
        json.dump(edl, f, ensure_ascii=False, indent=2)
    os.makedirs(out, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(out, f"reel_{ts}.mp4")
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    "--edl", plan, "--src", watch, "--out", outfile], check=True)
    return outfile


def main():
    ap = argparse.ArgumentParser(description="Auto-watcher: Drive folder → rendered reel")
    ap.add_argument("--watch", required=True, help="папка исходников (00 Исходники)")
    ap.add_argument("--out", required=True, help="папка выхода (01 Готовые)")
    ap.add_argument("--interval", type=int, default=20, help="период опроса, сек")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--once", action="store_true", help="один прогон и выход")
    a = ap.parse_args()
    watch = os.path.expanduser(a.watch)
    out = os.path.expanduser(a.out)
    print(f"👀 слежу: {watch}\n   →      {out}   (каждые {a.interval}s)")
    last = None
    while True:
        try:
            sig, items = snapshot(watch)
            if has_media(items) and sig != last:
                print("новые исходники — рендерю…")
                f = process(watch, out, a.fps)
                print("✅ готово:", f)
                last = sig
        except Exception as e:
            print("ошибка:", e)
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
