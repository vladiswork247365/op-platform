#!/usr/bin/env python3
"""Оркестратор контент-завода: сценарий → готовый ролик из 3 частей.

Связывает:
  сценарий (scriptwriter) → озвучка клон-голосом (ElevenLabs) → твои кадры авто →
  субтитры по таймингам голоса → плашки-акценты → фоновая музыка → ролик,
  который режется на 3 части для просмотра/правок, финал = целый ролик.

Всё мягко деградирует: нет ElevenLabs — build() вернёт None; нет ключа музыки —
соберётся без музыки.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time

import imageio_ffmpeg

import voiceover
try:
    import eleven
except Exception:
    eleven = None
try:
    import music
except Exception:
    music = None
try:
    import trending  # трендовый звук из библиотеки (буст охватов)
except Exception:
    trending = None
try:
    import shots    # «глаза»: Claude смотрит каждый клип
    import editor   # монтажёр: Claude раскладывает кадр на фразу
except Exception:
    shots = editor = None

FF = imageio_ffmpeg.get_ffmpeg_exe()
HERE = os.path.dirname(os.path.abspath(__file__))


def _beat_starts(beats):
    """Кумулятивные старты битов на таймлайне + общая длительность."""
    starts, t = [], 0.0
    for b in beats:
        starts.append(t)
        d = b["dur"] if "dur" in b else (b.get("out", 0) - b.get("in", 0)) / b.get("speed", 1.0)
        t += max(0.05, d)
    return starts, t


def _inject_cards(edl: dict, script: dict):
    """Плашки: хук — на вход, остальные — на момент 'at' (доля ролика) от режиссёра."""
    beats = edl.get("beats") or []
    if not beats:
        return
    starts, total = _beat_starts(beats)
    n = len(beats)

    def beat_at(frac):
        tt = min(max(0.0, frac), 1.0) * total
        idx = 0
        for j in range(n):
            if starts[j] <= tt:
                idx = j
        return idx

    hook = (script.get("hook") or "").strip()
    if hook:
        beats[0]["card"] = {"headline": hook, "label": "", "sub": "", "color": "red", "yf": 0.13}
    cards = script.get("cards") or []
    for k, c in enumerate(cards):
        at = c.get("at")
        bi = beat_at(at) if at is not None else min(n - 1, int((k + 1) / (len(cards) + 1) * n))
        if bi == 0 and hook:
            bi = min(n - 1, 1)          # не затирать хук
        while bi < n - 1 and beats[bi].get("card"):
            bi += 1                     # не класть две плашки на один бит
        beats[bi]["card"] = {"label": c.get("label", ""), "headline": c.get("headline", ""),
                             "sub": c.get("sub", ""), "color": c.get("color", "yellow"), "yf": 0.13}


_STRIP = ".,!?—:;«»\"'()"


def _apply_highlights(edl: dict, words):
    """Подсветить в субтитрах слова, выбранные режиссёром (highlight_words)."""
    hl = {w.strip(_STRIP).lower() for w in (words or []) if w.strip()}
    if not hl:
        return
    for b in edl.get("beats", []):
        for cue in (b.get("captions") or []):
            for ln in cue.get("lines", []):
                for w in ln.split():
                    if w.strip(_STRIP).lower() in hl:
                        cue["highlight"] = w.strip(_STRIP)
                        break


def _beats_meta(edl: dict):
    """Раскадровка для монтажёра: на каждый бит — что говорится + длина на таймлайне."""
    meta = []
    for i, b in enumerate(edl.get("beats", [])):
        seg = b["dur"] if "dur" in b else (b.get("out", 0) - b.get("in", 0)) / b.get("speed", 1.0)
        txt = " ".join(ln for cue in (b.get("captions") or []) for ln in cue.get("lines", []))
        meta.append({"i": i, "text": txt.strip(), "seg": round(max(0.4, seg), 2)})
    return meta


def _apply_shot_plan(edl: dict, plan: dict, by_file: dict) -> int:
    """Переписать биты по плану Claude: какой клип, момент старта, движение. → сколько применено.

    Субтитры/переходы/панч сохраняются (они завязаны на тайминги голоса).
    """
    beats = edl.get("beats", [])
    used = 0
    for i, b in enumerate(beats):
        p = plan.get(i)
        if not p:
            continue
        info = by_file.get(p["file"])
        if not info:
            continue
        seg = b["dur"] if "dur" in b else (b.get("out", 0) - b.get("in", 0)) / b.get("speed", 1.0)
        seg = round(max(0.4, seg), 2)
        cap, tr, punch = b.get("captions"), b.get("transition"), b.get("punch")
        first = (i == 0)
        mo = p.get("motion")
        if info["is_image"]:
            for k in ("in", "out", "speed"):
                b.pop(k, None)
            b["src"], b["dur"], b["audio"] = info["file"], seg, "mute"
            b["motion"] = mo if mo in ("kenburns_in", "kenburns_out") else (
                "kenburns_in" if i % 2 == 0 else "kenburns_out")
        else:
            avail = info.get("dur") or 0.0
            if avail < seg * 0.5:            # клип слишком короткий — не трогаем бит
                continue
            # логичная обрезка от Claude: берём кусок in→out, скоростью подгоняем под бит
            tin = min(max(0.0, p.get("in", 0.0)), max(0.0, avail - 0.2))
            tout = p.get("out")
            trim = (tout - tin) if isinstance(tout, (int, float)) and tout > tin \
                else min(seg, avail - tin)
            speed = min(2.0, max(0.5, (trim / seg) if seg > 0 else 1.0))
            actual = seg * speed             # столько секунд источника проиграем за бит
            if actual > avail:               # клип короче — берём весь, синхрон держим скоростью
                actual = avail
                speed = min(2.0, max(0.5, actual / seg))
                tin = 0.0
            elif tin + actual > avail:       # не вылезаем за конец клипа
                tin = max(0.0, avail - actual)
            b.pop("dur", None)
            b["src"], b["audio"] = info["file"], "mute"
            b["in"], b["out"] = round(tin, 3), round(tin + actual, 3)
            b["speed"] = round(speed, 3)
            if first:
                b["motion"], b["punch"] = "punch", 1.08
            else:
                b["motion"] = mo if mo in ("punch", "zoomin", "zoomout", "kick") else \
                    b.get("motion", "zoomin")
        if cap is not None:
            b["captions"] = cap
        if tr:
            b["transition"] = tr
        if punch and not first:
            b["punch"] = punch
        used += 1
    return used


def _mix_bg(video: str, music_file: str, out: str, gain_db: int = -18) -> str:
    """Подмешать фоновую музыку под голос (музыка тише, чуть глуше на пиках голоса)."""
    dur = voiceover.media_dur(video)
    fade = max(0.0, dur - 1.2)
    try:
        subprocess.run([FF, "-y", "-i", video, "-i", music_file, "-filter_complex",
                        f"[1:a]volume={gain_db}dB,afade=out:st={fade:.2f}:d=1.2[m];"
                        f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,dynaudnorm[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "160k", "-movflags", "+faststart", out], check=True,
                       capture_output=True)
        return out
    except Exception:
        return video   # не вышло — оставляем без музыки


def build(footage_dir: str, script: dict, out_dir: str, voice_id: str | None = None,
          gray: bool = False, mood: str = "energetic", fps: int = 30, status_cb=None,
          rtype: str = ""):
    """Собрать полный ролик по сценарию. → путь к ролику или None (нет озвучки)."""
    def _st(t):
        if status_cb:
            try:
                status_cb(t)
            except Exception:
                pass
    if not (eleven and eleven.have_key()):
        return None
    text = " ".join(s for s in (script.get("part1"), script.get("part2"),
                                script.get("part3")) if s).strip()
    if not text:
        return None
    _st("🎙 Озвучиваю сценарий твоим голосом…")
    audio = os.path.join(footage_dir, "_voice.mp3")
    res = eleven.tts_timed(text, audio, voice_id, settings=script.get("voice"))  # подача от Opus
    if not res:
        return None
    _, words = res
    total = voiceover.media_dur(audio)
    if total <= 0:
        return None
    _st("🎬 Собираю видеоряд под озвучку…")
    edl = voiceover.build_edl(footage_dir, audio, words, total, fps=fps, sub_y=0.8,
                             pace=script.get("pace", "medium"))            # темп от Opus
    if gray or script.get("grayscale"):                                    # ч/б от Opus
        edl["output"]["grayscale"] = True
    # Claude-монтаж: видит каждый клип и раскладывает какой кадр на какую фразу
    if shots and editor:
        try:
            _st("👁 Claude смотрит твои клипы…")
            clips = shots.analyze(footage_dir, status_cb=_st)
            if clips:
                _st("🎬 Раскладываю кадры под смысл (Claude-монтаж)…")
                plan = editor.plan_shots(_beats_meta(edl), clips, script, rtype)
                if plan:
                    n = _apply_shot_plan(edl, plan, {c["file"]: c for c in clips})
                    _st(f"🎬 Claude собрал раскадровку: кадров по смыслу — {n}")
        except Exception as e:
            sys.stderr.write(f"[factory_reel] shot-plan skipped: {type(e).__name__}: {e}\n")
    _inject_cards(edl, script)                                             # тайминг плашек от Opus
    _apply_highlights(edl, script.get("highlight_words"))                  # акцент-слова от Opus
    plan = os.path.join(footage_dir, "_factory.edl.json")
    with open(plan, "w", encoding="utf-8") as f:
        json.dump(edl, f, ensure_ascii=False, indent=2)
    os.makedirs(out_dir, exist_ok=True)
    reel = os.path.join(out_dir, f"reel_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    _st("🎨 Рендерю (озвучка + субтитры + плашки)…")
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"),
                    "--edl", plan, "--src", footage_dir, "--out", reel], check=True)
    # фоновая музыка: 1) трек, который прислал автор; иначе 2) Jamendo по настроению
    mf = _user_music(footage_dir)
    if not mf and trending and trending.have():
        _st("🎵 Беру трендовый звук под настроение…")
        mf = trending.pick(mood)
    if not mf and music and music.have_key():
        _st("🎵 Подбираю музыку…")
        mf = music.get_track(os.path.join(footage_dir, "_bg.mp3"), mood)
    if mf:
        _st("🎵 Накладываю музыку под голос…")
        mixed = os.path.join(out_dir, "_mixed.mp4")
        if _mix_bg(reel, mf, mixed) == mixed:
            try:
                os.replace(mixed, reel)
            except Exception:
                pass
    return reel


_AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}


def _user_music(footage_dir: str):
    """Трек, который прислал автор (аудио-файл среди исходников). None — если нет."""
    try:
        for f in sorted(os.listdir(footage_dir)):
            if f.startswith("_"):
                continue
            if os.path.splitext(f)[1].lower() in _AUDIO_EXT:
                return os.path.join(footage_dir, f)
    except Exception:
        pass
    return None


def split_three(reel: str, out_dir: str):
    """Порезать готовый ролик на 3 равные части (для просмотра/правок). → [p1,p2,p3]."""
    total = voiceover.media_dur(reel)
    if total <= 0:
        return []
    seg = total / 3.0
    parts = []
    for i in range(3):
        p = os.path.join(out_dir, f"part{i+1}.mp4")
        ss = round(i * seg, 2)
        t = round(seg if i < 2 else total - ss, 2)
        try:
            subprocess.run([FF, "-y", "-ss", f"{ss}", "-i", reel, "-t", f"{t}",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                            "-movflags", "+faststart", p], check=True, capture_output=True)
            parts.append(p)
        except Exception:
            pass
    return parts
