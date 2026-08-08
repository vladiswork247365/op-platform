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
import shutil
import subprocess
import sys
import tempfile
import time

import auto_edl
import dynamic_cut
import face_zone

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


def prepare(src, work):
    """Рабочая папка: видео поджимаем auto-editor'ом (убираем мёртвый воздух),
    фото/аудио копируем как есть."""
    for f in sorted(os.listdir(src)):
        if f.startswith((".", "_")):
            continue
        p = os.path.join(src, f)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(f)[1].lower()
        dst = os.path.join(work, f)
        if ext in auto_edl.VIDEO_EXT:
            _, changed = dynamic_cut.tighten(p, dst)
            print(f"  {'⚡ поджал' if changed else 'скопировал'} {f}")
        elif ext in (auto_edl.IMAGE_EXT | auto_edl.AUDIO_EXT):
            shutil.copy(p, dst)


def process(watch, out, fps, hook=None, grayscale=False):
    work = tempfile.mkdtemp(prefix="reels_work_")
    try:
        prepare(watch, work)
        edl = auto_edl.build_edl(work, fps=fps)
        if grayscale:
            edl.setdefault("output", {})["grayscale"] = True
        # автозона субтитров по лицу — не садить субтитры на лицо
        sy = None
        try:
            vids = [os.path.join(work, f) for f in sorted(os.listdir(work))
                    if os.path.splitext(f)[1].lower() in auto_edl.VIDEO_EXT]
            if vids:
                sy = face_zone.subtitle_y_fraction(vids[0])
                if sy:
                    print(f"  🙂 лицо найдено — субтитры на {int(sy*100)}% высоты (мимо лица)")
        except Exception as e:
            print("  (детектор лица пропущен:", str(e)[:60], ")")
        if sy:
            for b in edl.get("beats", []):
                for cue in (b.get("captions") or []):
                    cue.setdefault("yf", sy)
                if b.get("text") and b["text"].get("pos", "lower") == "lower":
                    b["text"].setdefault("yf", sy)
        # текстовое ТЗ пользователя → крупный хук в начале ролика (первый beat)
        if hook and edl.get("beats"):
            edl["beats"][0]["text"] = {
                "lines": auto_edl.wrap_words(hook, per=3, maxlines=2),
                "pos": "center", "size": 96}
        plan = os.path.join(work, "_auto.edl.json")
        with open(plan, "w", encoding="utf-8") as f:
            json.dump(edl, f, ensure_ascii=False, indent=2)
        os.makedirs(out, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        outfile = os.path.join(out, f"reel_{ts}.mp4")
        subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                        "--edl", plan, "--src", work, "--out", outfile], check=True)
        return outfile
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
