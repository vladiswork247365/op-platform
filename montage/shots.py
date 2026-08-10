#!/usr/bin/env python3
"""«Глаза» монтажёра: Claude смотрит каждый клип и описывает, что в кадре.

Для каждого видео берём 3 кадра (начало/середина/конец), для фото — сам кадр,
и через OpenRouter (vision-модель) получаем короткое описание: что происходит,
тип кадра (говорящая голова / b-roll / продукт / экран / текст), есть ли лицо,
динамика, теги. Это КАТАЛОГ, по которому Opus раскладывает какой кадр на какую
фразу (см. editor.py).

Результат кэшируется в footage_dir/_shots.json (ключ = имя+mtime), поэтому
повторные сборки того же сырья бесплатны. Без ключа/сети → analyze() вернёт []
(оркестратор откатится на подстановку кадров по порядку).
"""
from __future__ import annotations
import base64
import json
import os
import hashlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
_HERE = os.path.dirname(os.path.abspath(__file__))
# глобальный кэш анализа по СОДЕРЖИМОМУ файла — один и тот же клип не анализируем дважды
_GLOBAL_CACHE = os.path.join(_HERE, "library", "shots_cache.json")

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".hevc"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}

MODEL = (os.environ.get("OPENROUTER_VISION_MODEL")
         or os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-4.5")


def _content_key(path: str) -> str:
    """Ключ по содержимому: размер + md5 первых 256КБ (быстро, стабильно к переименованию)."""
    try:
        size = os.path.getsize(path)
        h = hashlib.md5()
        with open(path, "rb") as fh:
            h.update(fh.read(262144))
        return f"{size}:{h.hexdigest()}"
    except Exception:
        return ""


def _load_json(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass

SYS = (
    "Ты — ассистент виральных видеомонтажёров. Тебе дают несколько кадров ОДНОГО "
    "клипа. Опиши КОРОТКО, что на нём, чтобы монтажёр понял, куда его вставить в "
    "динамичный вертикальный Reels. Верни СТРОГО JSON без пояснений:\n"
    '{"desc": "одна фраза: что происходит / что в кадре",\n'
    ' "kind": "talking_head|b_roll|product|screen|text|other",\n'
    ' "has_face": true/false,        // есть ли крупно лицо человека\n'
    ' "energy": "high|medium|low",   // динамика/движение в кадре\n'
    ' "tags": ["3-6 ключевых слов"]}'
)


def _probe(path: str) -> str:
    return subprocess.run([FF, "-hide_banner", "-i", path],
                          capture_output=True, text=True).stderr


def _dur(path: str) -> float:
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", _probe(path))
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _grab(path: str, tmp: str, is_img: bool, dur: float):
    """Кадры для анализа: фото → 1 кадр; видео → 3 (нач./сер./кон.)."""
    frames = []
    if is_img:
        out = os.path.join(tmp, "f0.jpg")
        r = subprocess.run([FF, "-y", "-i", path, "-frames:v", "1",
                            "-vf", "scale=480:-1", "-q:v", "5", out], capture_output=True)
        if r.returncode == 0 and os.path.exists(out):
            frames.append(out)
        return frames
    for i, fr in enumerate((0.15, 0.5, 0.85)):
        t = max(0.1, (dur or 3.0) * fr)
        out = os.path.join(tmp, f"f{i}.jpg")
        r = subprocess.run([FF, "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                            "-vf", "scale=480:-1", "-q:v", "5", out], capture_output=True)
        if r.returncode == 0 and os.path.exists(out):
            frames.append(out)
    return frames


def _vision(frames, key, timeout=60):
    """Отправить кадры vision-модели → dict описания (или {} при сбое)."""
    content = [{"type": "text", "text": "Опиши этот клип для монтажа. Верни JSON."}]
    for f in frames:
        b64 = base64.b64encode(open(f, "rb").read()).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://systemop.pro", "X-Title": "OP Reels Eyes"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        raw = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        import re
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            return json.loads(raw)
        except Exception:
            i, j = raw.find("{"), raw.rfind("}")
            return json.loads(raw[i:j + 1]) if 0 <= i < j else {}
    except Exception as e:
        sys.stderr.write(f"[shots.vision] {type(e).__name__}: {str(e)[:120]}\n")
        return {}


def _norm(rec: dict, file: str, is_img: bool, dur: float) -> dict:
    kind = (rec.get("kind") or ("b_roll" if not is_img else "other")).strip().lower()
    if kind not in ("talking_head", "b_roll", "product", "screen", "text", "other"):
        kind = "b_roll"
    energy = (rec.get("energy") or "medium").strip().lower()
    if energy not in ("high", "medium", "low"):
        energy = "medium"
    tags = [str(t).strip() for t in (rec.get("tags") or []) if str(t).strip()][:6]
    return {"file": file, "is_image": is_img, "dur": round(dur, 2),
            "kind": kind, "has_face": bool(rec.get("has_face")),
            "energy": energy, "desc": (rec.get("desc") or "").strip()[:160], "tags": tags}


def analyze(footage_dir: str, api_key: str | None = None, status_cb=None) -> list[dict]:
    """Каталог клипов с описаниями. [] — если нет ключа/нечего анализировать."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return []
    files = []
    for f in sorted(os.listdir(footage_dir)):
        if f.startswith("_"):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext in VIDEO_EXT or ext in IMAGE_EXT:
            files.append(f)
    if not files:
        return []
    cache_path = os.path.join(footage_dir, "_shots.json")
    cache = _load_json(cache_path)          # кэш этой папки (имя:mtime)
    gcache = _load_json(_GLOBAL_CACHE)      # глобальный кэш по содержимому
    catalog, changed, gchanged, done = [], False, False, 0
    for idx, f in enumerate(files):
        full = os.path.join(footage_dir, f)
        try:
            mtime = int(os.path.getmtime(full))
        except OSError:
            mtime = 0
        ck = f"{f}:{mtime}"
        if ck in cache:
            catalog.append(cache[ck])
            continue
        conkey = _content_key(full)          # тот же клип (даже переименованный) — не анализируем
        if conkey and conkey in gcache:
            item = dict(gcache[conkey])
            item["file"] = f
            cache[ck] = item
            catalog.append(item)
            changed = True
            continue
        if status_cb:
            try:
                status_cb(f"👁 Claude смотрит клипы… {idx + 1}/{len(files)}")
            except Exception:
                pass
        ext = os.path.splitext(f)[1].lower()
        is_img = ext in IMAGE_EXT
        dur = 0.0 if is_img else _dur(full)
        with tempfile.TemporaryDirectory() as tmp:
            frames = _grab(full, tmp, is_img, dur)
            rec = _vision(frames, key) if frames else {}
        item = _norm(rec, f, is_img, dur)
        cache[ck] = item
        if conkey:
            gcache[conkey] = item
            gchanged = True
        catalog.append(item)
        changed = True
        done += 1
    if changed:
        _save_json(cache_path, cache)
    if gchanged:
        _save_json(_GLOBAL_CACHE, gcache)
    return catalog


def catalog_text(clips: list[dict]) -> str:
    """Каталог клипов текстом для промпта режиссёра-монтажёра."""
    lines = []
    for c in clips:
        typ = "фото" if c["is_image"] else f"видео {c['dur']:.1f}с"
        face = "лицо:да" if c["has_face"] else "лицо:нет"
        tg = (" | теги: " + ", ".join(c["tags"])) if c["tags"] else ""
        lines.append(f'{c["file"]} | {typ} | {c["kind"]} | {face} | динамика:{c["energy"]}'
                     f' | "{c["desc"]}"{tg}')
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Глаза монтажёра: описать клипы в папке")
    ap.add_argument("dir")
    a = ap.parse_args()
    cat = analyze(a.dir, status_cb=lambda t: print(t))
    if not cat:
        print("пусто (нет ключа OPENROUTER_API_KEY / нет клипов / нет сети)")
    else:
        print(catalog_text(cat))
