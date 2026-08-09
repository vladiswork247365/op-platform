#!/usr/bin/env python3
"""Предиктор виральности ДО публикации: Claude смотрит готовый ролик глазами.

После сборки (но ещё ДО постинга) снимаем несколько кадров ролика + даём сценарий,
и Opus-vision оценивает виральный потенциал: сила хука, риск слить удержание,
читаемость, паттерн-интеррапт, CTA. Возвращает балл, слабые места и КОНКРЕТНЫЕ
правки — чтобы усилить ролик до публикации, а не узнать об ошибках через 6 часов.

Без ключа/сети → None (бот просто пропустит проверку). OpenRouter + stdlib.
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

try:
    import reel_types
except Exception:
    reel_types = None

FF = imageio_ffmpeg.get_ffmpeg_exe()
MODEL = (os.environ.get("OPENROUTER_VISION_MODEL")
         or os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-4.5")

SYS = (
    "Ты — строгий предиктор виральности вертикальных Reels для русскоязычной аудитории "
    "(собственники бизнеса, РОПы). Тебе дают КАДРЫ готового ролика по порядку и его "
    "сценарий. Оцени шанс ролика зайти (досмотр >60%, репосты, сохранения) ДО публикации "
    "и дай конкретику, что усилить. Смотри на: силу первых 2 сек (хук — стоп-скролл?), "
    "читаемость субтитров/плашек, динамику и смену кадра, паттерн-интеррапты, ясность "
    "мысли, силу оффера/CTA. Будь честным и жёстким — лучше поругать сейчас, чем слить показы.\n\n"
    "Верни СТРОГО JSON без пояснений:\n"
    '{\n'
    '  "score": 1-10,                 // виральный потенциал\n'
    '  "tier": "S|A|B|C",             // грубая оценка\n'
    '  "hook": "оценка первых 2 сек — стопнет ли скролл",\n'
    '  "retention_risk": "где вероятнее всего сольётся внимание",\n'
    '  "strengths": ["1-3 сильные стороны"],\n'
    '  "weak_spots": ["2-4 слабых места"],\n'
    '  "fixes": ["2-4 конкретные правки ДО публикации"],\n'
    '  "sound": "какой ТРЕНДОВЫЙ звук из Инсты добавить вручную под этот ролик: '
    'вайб/жанр/темп и где должен бить дроп (под хук/оффер)",\n'
    '  "verdict": "1-2 фразы: постить или переделать и что"\n'
    '}'
)


def _grab(path: str, tmp: str, n: int = 6):
    dur = _dur(path) or 10.0
    frames = []
    for i in range(n):
        fr = (i + 0.5) / n
        out = os.path.join(tmp, f"pv_{i}.jpg")
        t = max(0.1, dur * fr)
        r = subprocess.run([FF, "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                            "-vf", "scale=540:-1", "-q:v", "4", out], capture_output=True)
        if r.returncode == 0 and os.path.exists(out):
            frames.append(out)
    return frames


def _dur(path: str) -> float:
    p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _ctx(script: dict | None, rtype: str) -> str:
    parts = []
    if reel_types and reel_types.valid(rtype):
        parts.append(f"ФОРМАТ: {reel_types.title(rtype)}")
    if script:
        if script.get("hook"):
            parts.append(f'ХУК: {script["hook"]}')
        body = " / ".join(s for s in (script.get("part1"), script.get("part2"),
                                      script.get("part3")) if s)
        if body:
            parts.append("Сценарий: " + body[:600])
        if script.get("cta_word"):
            parts.append(f'CTA: {script["cta_word"]}')
    return "\n".join(parts)


def _parse(raw: str):
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    try:
        return json.loads(raw)
    except Exception:
        i, j = raw.find("{"), raw.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(raw[i:j + 1])
            except Exception:
                return None
    return None


def check(reel_path: str, script: dict | None = None, rtype: str = "",
          api_key: str | None = None, timeout: int = 90) -> dict | None:
    """Оценить виральность готового ролика ДО публикации. → dict|None."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key or not os.path.exists(reel_path):
        return None
    import urllib.request
    ctx = _ctx(script, rtype)
    with tempfile.TemporaryDirectory() as tmp:
        frames = _grab(reel_path, tmp)
        if not frames:
            return None
        content = [{"type": "text", "text": ((ctx + "\n\n" if ctx else "")
                    + "Оцени виральный потенциал этого ролика ДО публикации. Верни JSON.")}]
        for f in frames:
            b64 = base64.b64encode(open(f, "rb").read()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        body = json.dumps({
            "model": MODEL,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": content}],
            "temperature": 0.3,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": "https://systemop.pro", "X-Title": "OP Reels Previral"})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=timeout))
            raw = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            return _parse(raw)
        except Exception as e:
            sys.stderr.write(f"[previral] {type(e).__name__}: {str(e)[:150]}\n")
            return None


def as_text(v: dict) -> str:
    if not v:
        return ""
    li = lambda a: "\n".join(f"  • {x}" for x in (a or []))
    out = [f"🔮 ВИРАЛЬНОСТЬ (до публикации): {v.get('score', '?')}/10"
           + (f" · {v['tier']}" if v.get("tier") else "")]
    if v.get("hook"):
        out.append(f"🎣 Хук: {v['hook']}")
    if v.get("retention_risk"):
        out.append(f"⏱ Риск слива: {v['retention_risk']}")
    if v.get("strengths"):
        out.append("💪 Сильное:\n" + li(v["strengths"]))
    if v.get("weak_spots"):
        out.append("⚠️ Слабое:\n" + li(v["weak_spots"]))
    if v.get("fixes"):
        out.append("🛠 Усилить до постинга:\n" + li(v["fixes"]))
    if v.get("sound"):
        out.append(f"🎵 Трендовый звук: {v['sound']}")
    if v.get("verdict"):
        out.append(f"\n💡 {v['verdict']}")
    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Предиктор виральности ролика до публикации")
    ap.add_argument("reel")
    ap.add_argument("--type", default="")
    a = ap.parse_args()
    v = check(a.reel, rtype=a.type)
    print(as_text(v) if v else "нет ключа/сети/кадров")
