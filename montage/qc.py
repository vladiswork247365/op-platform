#!/usr/bin/env python3
"""Авто-контроль качества готового ролика — «вторые мозги».

После рендера пересматривает результат и говорит, всё ли хорошо. Два уровня:

  1) ТЕХНИКА (без ключей, детерминированно): формат 9:16 1080x1920, длительность
     в разумных рамках, наличие звука, остаточные чёрные полосы (letterbox),
     длинные чёрные кадры.
  2) AI-РЕВЬЮ КАДРОВ (если есть OPENROUTER_API_KEY): семплим несколько кадров →
     vision-модель смотрит глазами и говорит, нет ли проблем: субтитры НА ЛИЦЕ,
     текст обрезан краем, нечитаемо, пустой/чёрный кадр.

Возвращает вердикт:
  {"ok": bool,
   "issues": [{"code","severity","msg"}],
   "fixes": {"sub_y": 0.86}   # подсказки движку для переделки (что можно поправить)
  }

Всё мягко деградирует: нет ffmpeg/ключа/сети → проверка пропускается, ok=True.
"""
from __future__ import annotations
import base64
import json
import os
import re
import subprocess
import sys
import tempfile

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
# по умолчанию — та же модель, что у режиссёра (Opus). Можно удешевить контроль,
# задав OPENROUTER_VISION_MODEL=openai/gpt-4o-mini (кадры-картинки дороже текста).
MODEL = (os.environ.get("OPENROUTER_VISION_MODEL")
         or os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-4.1")


def _probe(path: str) -> str:
    return subprocess.run([FF, "-hide_banner", "-i", path],
                          capture_output=True, text=True).stderr


def _dims(info: str):
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", info)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _duration(info: str) -> float:
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def tech_check(path: str):
    """Детерминированные технические проверки. → (issues, fixes)."""
    issues, fixes = [], {}
    if not os.path.exists(path):
        return [{"code": "missing", "severity": "hard", "msg": "файл не создан"}], fixes
    info = _probe(path)
    w, h = _dims(info)
    dur = _duration(info)
    if (w, h) != (1080, 1920):
        issues.append({"code": "format", "severity": "hard",
                       "msg": f"формат {w}x{h}, а нужен 1080x1920 (9:16)"})
    if dur and not (5.0 <= dur <= 95.0):
        issues.append({"code": "duration", "severity": "soft",
                       "msg": f"длительность {dur:.0f}с вне диапазона 5–95с"})
    if "Audio:" not in info:
        issues.append({"code": "noaudio", "severity": "hard", "msg": "нет звуковой дорожки"})
    # остаточные чёрные полосы (letterbox) на готовом ролике
    try:
        p = subprocess.run([FF, "-hide_banner", "-i", path, "-vf", "cropdetect=24:2:0",
                            "-frames:v", "60", "-f", "null", "-"], capture_output=True, text=True)
        crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", p.stderr)
        if crops and w and h:
            from collections import Counter
            cw, ch, _, _ = (int(x) for x in Counter(crops).most_common(1)[0][0])
            if ch < h * 0.92 or cw < w * 0.92:
                issues.append({"code": "bars", "severity": "soft",
                               "msg": "видны чёрные полосы по краям"})
    except Exception:
        pass
    # длинные чёрные кадры (провал картинки)
    try:
        p = subprocess.run([FF, "-hide_banner", "-i", path, "-vf",
                            "blackdetect=d=0.6:pic_th=0.98", "-an", "-f", "null", "-"],
                           capture_output=True, text=True)
        if re.search(r"black_start", p.stderr):
            issues.append({"code": "blackframe", "severity": "soft",
                           "msg": "есть затяжные чёрные кадры"})
    except Exception:
        pass
    return issues, fixes


def _grab_frames(path: str, tmp: str, at_fracs=(0.12, 0.4, 0.7, 0.92)):
    info = _probe(path)
    dur = _duration(info) or 10.0
    frames = []
    for i, fr in enumerate(at_fracs):
        out = os.path.join(tmp, f"qc_{i}.jpg")
        t = max(0.1, dur * fr)
        r = subprocess.run([FF, "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                            "-vf", "scale=540:-1", "-q:v", "4", out],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out):
            frames.append(out)
    return frames


AI_SYS = (
    "Ты — строгий контролёр качества коротких вертикальных Reels. Тебе дают несколько "
    "кадров одного ролика. Оцени ТОЛЬКО видимые дефекты и верни СТРОГО JSON без пояснений:\n"
    '{"subtitle_on_face": bool,  // субтитры/плашка налезают на лицо человека\n'
    ' "text_cut_off": bool,      // текст обрезан краем кадра\n'
    ' "unreadable": bool,        // субтитры плохо читаются (контраст/наложение)\n'
    ' "black_or_empty": bool,    // пустой/чёрный/битый кадр\n'
    ' "notes": "одна короткая фраза"}'
)


def ai_check(path: str, api_key: str | None = None, timeout: int = 60):
    """AI-ревью кадров через OpenRouter vision. → (issues, fixes) или ([],{}) если нет ключа."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return [], {}
    import urllib.request
    issues, fixes = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        frames = _grab_frames(path, tmp)
        if not frames:
            return [], {}
        content = [{"type": "text", "text": "Проверь кадры ролика на дефекты. Верни JSON."}]
        for f in frames:
            b64 = base64.b64encode(open(f, "rb").read()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        body = json.dumps({
            "model": MODEL,
            "messages": [{"role": "system", "content": AI_SYS},
                         {"role": "user", "content": content}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": "https://platform.systemop.top", "X-Title": "OP Reels QC"})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=timeout))
            v = json.loads(r["choices"][0]["message"]["content"])
        except Exception as e:
            sys.stderr.write(f"[qc.ai] недоступен ({type(e).__name__}: {str(e)[:90]})\n")
            return [], {}
    if v.get("subtitle_on_face"):
        issues.append({"code": "sub_on_face", "severity": "soft", "msg": "субтитры на лице"})
        fixes["sub_y"] = 0.86              # заставить субтитры уйти ниже
    if v.get("text_cut_off"):
        issues.append({"code": "text_cut", "severity": "soft", "msg": "текст обрезан краем"})
    if v.get("unreadable"):
        issues.append({"code": "unreadable", "severity": "soft", "msg": "субтитры плохо читаются"})
    if v.get("black_or_empty"):
        issues.append({"code": "black_ai", "severity": "soft", "msg": "пустой/чёрный кадр"})
    note = (v.get("notes") or "").strip()
    if note:
        fixes["note"] = note[:120]
    return issues, fixes


def review(path: str, use_ai: bool = True):
    """Полный вердикт: техника + (опц.) AI-ревью кадров."""
    issues, fixes = tech_check(path)
    if use_ai:
        try:
            ai_i, ai_f = ai_check(path)
            issues += ai_i
            fixes.update(ai_f)
        except Exception as e:
            sys.stderr.write(f"[qc] AI-ревью пропущено: {str(e)[:80]}\n")
    hard = [i for i in issues if i["severity"] == "hard"]
    return {"ok": not issues, "hard": bool(hard), "issues": issues, "fixes": fixes}


def summary(verdict: dict) -> str:
    """Короткая строка вердикта для Telegram."""
    if verdict.get("ok"):
        return "🧠 Контроль качества: ✅ без замечаний"
    parts = ", ".join(i["msg"] for i in verdict.get("issues", [])[:4])
    return f"🧠 Контроль качества: нашёл — {parts}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 qc.py <video.mp4>")
        sys.exit(0)
    v = review(sys.argv[1])
    print(json.dumps(v, ensure_ascii=False, indent=2))
