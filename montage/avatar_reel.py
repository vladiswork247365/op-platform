#!/usr/bin/env python3
"""Монтаж поверх ГОВОРЯЩЕГО аватара — голос аватара = основа, липсинк не трогаем.

Как в топ-роликах «спикер + вставки экрана продукта»:
  • База — главный говорящий клип (лицо + собственный звук). Его голос идёт НЕПРЕРЫВНО.
  • Субтитры — по ЕГО речи (whisper), мимо лица (face_zone), минимал-стиль.
  • Экранки/панель (лицо:нет) — вставки-КАТ-ЭВЕИ ПОВЕРХ картинки на нужных секундах;
    звук аватара при этом продолжается (кат-эвей только по видео).
  • Сверху — фоновая музыка (тише голоса).

Мягко деградирует: нет вставок → просто говорящая голова с субтитрами; нет whisper →
субтитров нет, но ролик соберётся; нет музыки → без музыки.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
import time

import imageio_ffmpeg

try:
    import transcribe
except Exception:
    transcribe = None
try:
    import face_zone
except Exception:
    face_zone = None
try:
    import shots
except Exception:
    shots = None
try:
    import music as _music
except Exception:
    _music = None
try:
    import cards as _cards_mod
except Exception:
    _cards_mod = None

FF = imageio_ffmpeg.get_ffmpeg_exe()
HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".hevc"}


def _dur(path: str) -> float:
    try:
        p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True)
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", p.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def _has_audio(path: str) -> bool:
    try:
        p = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True)
        return "Audio:" in p.stderr
    except Exception:
        return False


def _videos(footage_dir: str):
    out = []
    for f in sorted(os.listdir(footage_dir)):
        if f.startswith((".", "_")):
            continue
        if os.path.splitext(f)[1].lower() in VIDEO_EXT:
            out.append(os.path.join(footage_dir, f))
    return out


def classify(footage_dir: str):
    """→ (base_path, [insert_dicts]).  insert = {'path','dur','desc'}.

    База — говорящий клип с лицом и звуком (самый длинный). Вставки — клипы без лица
    (экран/панель/продукт). Если shots недоступен — эвристика по лицу/звуку.
    """
    vids = _videos(footage_dir)
    if not vids:
        return None, []
    info = {}
    if shots:
        try:
            for c in (shots.analyze(footage_dir) or []):
                if not c.get("is_image"):
                    info[os.path.join(footage_dir, c["file"])] = c
        except Exception:
            info = {}

    def has_face(p):
        c = info.get(p)
        if c is not None:
            return bool(c.get("has_face"))
        if face_zone:                                   # эвристика: нашли лицо → говорящий
            try:
                return face_zone._face_box_fraction(p) is not None
            except Exception:
                pass
        return _has_audio(p)                            # последний резерв: есть звук → говорящий

    talking = [p for p in vids if has_face(p) and _has_audio(p)]
    base = max(talking or vids, key=_dur)
    inserts = []
    for p in vids:
        if p == base:
            continue
        c = info.get(p) or {}
        if c.get("has_face"):                           # ещё одна говорящая голова — не вставка
            continue
        inserts.append({"path": p, "dur": _dur(p), "desc": c.get("desc", "")})
    return base, inserts


def _phrase_cues(words, per: int = 3, gap: float = 0.6):
    """Слова → короткие фразы-каптионы [{t0,t1,text}] (по ~per слов, рвём на паузах)."""
    cues, cur = [], []
    for w in words or []:
        if not (w.get("word") or "").strip():
            continue
        if cur and (len(cur) >= per or w["start"] - cur[-1]["end"] > gap):
            cues.append(cur)
            cur = []
        cur.append(w)
    if cur:
        cues.append(cur)
    out = []
    for ch in cues:
        out.append({"t0": round(ch[0]["start"], 3), "t1": round(ch[-1]["end"], 3),
                    "text": " ".join(w["word"] for w in ch).strip()})
    return out


def plan_inserts(base_dur: float, cues, inserts, max_frac: float = 0.4,
                 seg: float = 2.4, hook_guard: float = 3.5, tail_guard: float = 1.5):
    """Расставить экранки-вставки по таймлайну (эвристика): растянуть по середине ролика,
    привязать к началу фразы, каждая ~seg сек, суммарно не более max_frac ролика.

    Совпадение по смыслу: если у вставки есть описание — ставим у фразы с общими словами.
    → [{'t0','t1','path','cin','cout'}] отсортировано по времени.
    """
    if not inserts or base_dur <= 0:
        return []
    budget = base_dur * max_frac
    # кандидатные моменты: начала фраз в безопасной зоне; если субтитров нет — равномерно
    cand = [(c["t0"], c["text"]) for c in (cues or [])
            if hook_guard <= c["t0"] <= base_dur - tail_guard - 1.0]
    if not cand:
        span0, span1 = hook_guard, base_dur - tail_guard - seg
        if span1 > span0:
            n = len(inserts)
            cand = [(round(span0 + (span1 - span0) * (i + 1) / (n + 1), 2), "")
                    for i in range(n)]
    if not cand:
        return []
    plan, used, taken = [], 0.0, []

    def _cue_for(desc, prefer_frac):
        words = {w for w in re.findall(r"[а-яёa-z]+", (desc or "").lower()) if len(w) > 3}
        best, best_score = None, -1
        for t0, text in cand:
            if any(abs(t0 - tk) < seg for tk in taken):
                continue
            overlap = len(words & {w for w in re.findall(r"[а-яёa-z]+", text.lower())})
            near = 1.0 - abs(t0 / base_dur - prefer_frac)
            score = overlap * 2 + near
            if score > best_score:
                best, best_score = t0, score
        return best

    n = len(inserts)
    for i, ins in enumerate(inserts):
        if used + seg > budget:
            break
        prefer = (i + 1) / (n + 1)                      # растягиваем по ролику
        t0 = _cue_for(ins.get("desc"), prefer)
        if t0 is None:
            continue
        length = min(seg, base_dur - tail_guard - t0, ins["dur"])
        if length < 1.0:
            continue
        cin = max(0.0, min(0.5, ins["dur"] - length))   # чуть от начала клипа, если можно
        plan.append({"t0": round(t0, 3), "t1": round(t0 + length, 3),
                     "path": ins["path"], "cin": round(cin, 3), "cout": round(cin + length, 3)})
        taken.append(t0)
        used += length
    plan.sort(key=lambda x: x["t0"])
    return plan


def plan_cards(cues, base_dur, timeout: int = 60):
    """Opus вытаскивает 3–5 сильных коротких фраз-акцентов из речи → плашки сверху кадра
    (как в топ-роликах: «АНАЛИЗ 100% ЗВОНКОВ», «КОНТЕКСТ ЖИВ»). → [{text,t0,t1}] или []."""
    if os.environ.get("CARDS", "on").strip().lower() in ("off", "0", "no", "false"):
        return []
    key = os.environ.get("OPENROUTER_API_KEY")
    text = " ".join(c["text"] for c in (cues or [])).strip()
    if not key or not text or base_dur <= 0:
        return []
    import json
    import urllib.request
    model = os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-4.5"
    sys_p = ("Ты — монтажёр виральных Reels. Из РАСШИФРОВКИ речи выбери 3–5 самых сильных "
             "коротких фраз-АКЦЕНТОВ (1–3 слова, КАПСОМ, как крупная плашка сверху кадра: "
             "«АНАЛИЗ 100% ЗВОНКОВ», «КОНТЕКСТ ЖИВ», «ЗДОРОВЬЕ СДЕЛКИ»). Каждая — на своём "
             "моменте ролика. Верни СТРОГО JSON без пояснений: "
             '{"cards":[{"text":"КОРОТКАЯ ФРАЗА","at":0.0}]} где at — доля ролика 0..1.')
    body = json.dumps({"model": model, "temperature": 0.5, "max_tokens": 600,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": sys_p},
                                    {"role": "user", "content": "РАСШИФРОВКА:\n" + text[:2000]}]
                       }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://systemop.pro", "X-Title": "OP Reels Avatar Cards"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        raw = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        data = json.loads(raw)
    except Exception as e:
        sys.stderr.write(f"[avatar_reel.cards] {type(e).__name__}: {str(e)[:120]}\n")
        return []
    out, taken = [], []
    starts = [c["t0"] for c in cues]
    for cd in (data.get("cards") or [])[:5]:
        txt = (cd.get("text") or "").strip()
        if not txt:
            continue
        try:
            frac = max(0.0, min(1.0, float(cd.get("at", 0.5))))
        except (TypeError, ValueError):
            frac = 0.5
        target = frac * base_dur
        t0 = min(starts, key=lambda s: abs(s - target)) if starts else target
        if any(abs(t0 - t) < 1.6 for t in taken):        # не наслаивать плашки
            continue
        taken.append(t0)
        out.append({"text": txt[:40], "t0": round(t0, 2),
                    "t1": round(min(base_dur, t0 + 2.0), 2)})
    out.sort(key=lambda x: x["t0"])
    return out


_ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Min,{font},{size},&H00FFFFFF,&H00000000,&H64000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},5,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(cues, out_path: str, yf: float = 0.63):
    """Субтитры в ASS под стиль SUB_STYLE: big (жирные белые строчными, дефолт) / minimal (тонкие).
    Белые, тёмная обводка, по центру мимо лица, строчными."""
    style = os.environ.get("SUB_STYLE", "big").strip().lower()
    minimal = style in ("minimal", "min", "thin", "clean", "premium")
    font = os.environ.get("SUB_ASS_FONT", "Arial")
    if minimal:
        size = int(os.environ.get("SUB_SIZE", str(max(28, int(W * 0.045)))))
        bold, outline, shadow = 0, 2, 1
    else:                                          # big — жирные крупные с плотной обводкой
        size = int(os.environ.get("SUB_SIZE", str(max(34, int(W * 0.056)))))
        bold, outline, shadow = -1, 3, 1
    y = int(max(0.2, min(0.9, yf)) * H)
    head = _ASS_HEAD.format(W=W, H=H, font=font, size=size, bold=bold, outline=outline, shadow=shadow)
    lines = [head]
    for c in cues:
        txt = c["text"].replace("\n", " ").strip().lower()
        txt = txt.replace("{", "(").replace("}", ")")
        if not txt:
            continue
        lines.append(f"Dialogue: 0,{_ass_ts(c['t0'])},{_ass_ts(c['t1'])},Min,,0,0,0,,"
                     f"{{\\an5\\pos({W // 2},{y})}}{txt}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def _norm_base(base: str, out: str, fps: int = 30):
    """Привести базу к 1080x1920 (fill+crop), сохранить звук."""
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"setsar=1,fps={fps},format=yuv420p")
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", base,
                    "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out],
                   check=True)
    return out


def _mix_music(video: str, music_file: str, out: str, gain_db: int = -18):
    """Подмешать музыку под голос (тише, с фейдом на конце)."""
    dur = _dur(video)
    fade = max(0.0, dur - 1.2)
    try:
        subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", video,
                        "-i", music_file, "-filter_complex",
                        f"[1:a]volume={gain_db}dB,afade=out:st={fade:.2f}:d=1.2[m];"
                        f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,dynaudnorm[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "160k", "-movflags", "+faststart", out], check=True)
        return out
    except Exception as e:
        sys.stderr.write(f"[avatar_reel.music] {type(e).__name__}: {str(e)[:120]}\n")
        return video


def build(footage_dir: str, out_dir: str, script: dict | None = None, status_cb=None,
          fps: int = 30, mood: str = "energetic", bake_music: bool = True):
    """Собрать ролик поверх говорящего аватара. → путь к ролику или None."""
    def _st(t):
        if status_cb:
            try:
                status_cb(t)
            except Exception:
                pass

    base, inserts = classify(footage_dir)
    if not base:
        _st("❌ Не нашёл говорящий клип (аватар).")
        return None
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "_avatar_tmp")
    os.makedirs(tmp, exist_ok=True)

    _st("🎬 Готовлю базу (голос аватара — без изменений)…")
    normed = _norm_base(base, os.path.join(tmp, "base.mp4"), fps)
    base_dur = _dur(normed)

    # субтитры по речи аватара
    cues, yf = [], float(os.environ.get("SUB_Y", "0.63"))
    if transcribe:
        _st("📝 Распознаю речь для субтитров…")
        words = transcribe.transcribe_words(base)
        cues = _phrase_cues(words) if words else []
    if face_zone and not os.environ.get("SUB_Y"):
        try:
            fy = face_zone.subtitle_y_fraction(base)
            if fy:
                yf = fy
        except Exception:
            pass

    # план вставок-экранок
    iplan = plan_inserts(base_dur, cues, inserts) if inserts else []
    if inserts:
        _st(f"🖥 Врезаю экранки: {len(iplan)} вставок(и) по смыслу")

    # плашки-акценты из речи (как в референсе): Opus вытаскивает сильные короткие фразы
    cplan = plan_cards(cues, base_dur) if cues else []
    cpngs = []
    if cplan and _cards_mod:
        for i, cd in enumerate(cplan):
            png = os.path.join(tmp, f"card_{i}.png")
            try:
                _cards_mod.render_card(cd["text"], out_path=png, w=W, h=H, y_frac=0.11)
                cpngs.append({"png": png, "t0": cd["t0"], "t1": cd["t1"]})
            except Exception:
                pass
    if cpngs:
        _st(f"🟥 Плашки-акценты: {len(cpngs)}")

    # рендер: база + экранки-кат-эвеи + плашки + субтитры, звук аватара — как есть
    _st("🎨 Собираю картинку (кат-эвеи + плашки + субтитры)…")
    inputs = ["-i", normed]
    for it in iplan:
        inputs += ["-i", it["path"]]
    card_base = 1 + len(iplan)                          # индекс первого инпута-плашки
    for cp in cpngs:
        inputs += ["-loop", "1", "-t", f"{base_dur:.3f}", "-i", cp["png"]]
    parts, cur = [], "[0:v]"
    for k, it in enumerate(iplan, start=1):
        parts.append(
            f"[{k}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"setsar=1,fps={fps},trim=start={it['cin']}:end={it['cout']},"
            f"setpts=PTS-STARTPTS+{it['t0']}/TB[ins{k}]")
    for k, it in enumerate(iplan, start=1):
        nxt = f"[v{k}]"
        parts.append(f"{cur}[ins{k}]overlay=0:0:enable='between(t,{it['t0']},{it['t1']})'"
                     f":eof_action=pass{nxt}")
        cur = nxt
    for j, cp in enumerate(cpngs):                      # плашки поверх (верх кадра)
        idx = card_base + j
        parts.append(f"[{idx}:v]format=rgba[cin{j}]")
        nxt = f"[c{j}]"
        parts.append(f"{cur}[cin{j}]overlay=0:0:enable='between(t,{cp['t0']},{cp['t1']})'"
                     f":eof_action=pass{nxt}")
        cur = nxt
    ass = build_ass(cues, os.path.join(tmp, "subs.ass"), yf) if cues else None
    if ass:
        esc = ass.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        parts.append(f"{cur}subtitles='{esc}'[vout]")
        vmap = "[vout]"
    else:
        if cur == "[0:v]":                      # нет ни вставок, ни субтитров — прогоним через null
            parts.append("[0:v]null[vout]")
            vmap = "[vout]"
        else:
            vmap = cur
    fc = ";".join(parts)
    silent = os.path.join(tmp, "silent.mp4")
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error", *inputs,
           "-filter_complex", fc, "-map", vmap, "-map", "0:a?",
           "-t", f"{base_dur:.3f}", "-r", str(fps),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", silent]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        sys.stderr.write("[avatar_reel] ffmpeg FAIL:\n" + (e.stderr or "")[-1500:] + "\n")
        return None

    out = os.path.join(out_dir, f"avatar_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    if bake_music and _music and _music.have_local():
        _st("🎵 Кладу музыку под голос…")
        mf = _music.local_pick(mood)
        if mf and _mix_music(silent, mf, out) == out:
            return out
    os.replace(silent, out)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Монтаж поверх говорящего аватара (голос — основа)")
    ap.add_argument("footage_dir")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--mood", default="energetic")
    a = ap.parse_args()
    r = build(a.footage_dir, a.out, status_cb=lambda t: print(t), mood=a.mood)
    print("готово:", r or "не собралось")
