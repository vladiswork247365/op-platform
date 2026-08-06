#!/usr/bin/env python3
"""Умный отбор моментов и хука по транскрипту (рычаг №1 досмотра).

Заменяет «бери самый длинный клип, режь по 3с» на «выбери самый цепляющий
момент и лучший хук». Эвристика виральности работает офлайн без ключей;
если задан OPENROUTER_API_KEY — ранжирование уточняет LLM.

Вход — слова с таймингами [{'start','end','word'}] (из transcribe.py).
"""
from __future__ import annotations
import json
import os
import re
import sys

# сигналы «залетаемости» в русской речи (хук/любопытство/сила/эмоция)
HOOK_WORDS = set((
    "секрет секрета ошибка ошибку ошибки никто никогда почему как правда деньги бесплатно "
    "главное важно запомни представь смотри слушай вот именно результат проблема решение "
    "фишка лайфхак способ метод система быстро сразу прямо сейчас нельзя надо стоп внимание "
    "миллион тысяч процентов раз навсегда впервые единственный лучший худший опасно"
).split())
FILLER_WORDS = set("ну вот типа короче значит просто ээ эээ мм это самое бы блин ваще вообщем".split())
POWER_RE = re.compile(r"\d")


def _norm(w):
    return re.sub(r"[^\wа-яё]", "", w.lower())


def seg_score(text: str) -> int:
    """Оценка виральности отрезка речи 0..100 (эвристика)."""
    words = [_norm(w) for w in text.split()]
    words = [w for w in words if w]
    if not words:
        return 0
    score = 30
    if "?" in text:
        score += 18
    if "!" in text:
        score += 8
    if POWER_RE.search(text):
        score += 14                       # цифры/факты
    hooks = sum(1 for w in words if w in HOOK_WORDS)
    score += min(30, hooks * 9)
    filler = sum(1 for w in words if w in FILLER_WORDS)
    score -= min(22, filler * 7)          # штраф за воду/филлер
    n = len(words)
    if 6 <= n <= 30:
        score += 8                        # осмысленная законченная фраза
    return max(0, min(100, score))


def _spans(words, max_words):
    """Псевдо-фразы: режем по крупным паузам между словами."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 1.0
        if gap > 0.45 or len(cur) >= max_words:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def best_hook(words, within_sec: float = 12.0, max_words: int = 7):
    """→ (lines, highlight): сильнейшая короткая фраза для хука из начала клипа."""
    head = [w for w in words if w["start"] <= within_sec]
    best, best_s = None, -1
    for span in _spans(head or words[:20], max_words):
        text = " ".join(w["word"] for w in span)
        s = seg_score(text)
        if s > best_s:
            best, best_s = span, s
    if not best:
        return None, None
    toks = [w["word"] for w in best]
    lines = [" ".join(toks[i:i + 3]) for i in range(0, len(toks), 3)][:2]
    hl = max(toks, key=len).strip(".,!?—:;«»\"'()")
    return lines, hl


def rank_windows(words, win_sec: float = 40.0, stride_sec: float = 12.0):
    """Кластеризация речи в окна и скоринг → [(start, end, score)] по убыванию."""
    if not words:
        return []
    t0, tN = words[0]["start"], words[-1]["end"]
    out = []
    t = t0
    while t < tN:
        seg = [w for w in words if t <= w["start"] < t + win_sec]
        if seg:
            text = " ".join(w["word"] for w in seg)
            out.append((round(seg[0]["start"], 2), round(seg[-1]["end"], 2), seg_score(text)))
        t += stride_sec
    out.sort(key=lambda x: -x[2])
    return out


def best_window(words, target_len: float = 34.0):
    """→ (start, end): лучший непрерывный кусок под хронометраж ролика."""
    ranked = rank_windows(words, win_sec=max(20.0, target_len), stride_sec=10.0)
    if not ranked:
        return 0.0, (words[-1]["end"] if words else target_len)
    s, e, _ = ranked[0]
    return s, e


def llm_rank(segments):
    """Опц.: уточнить ранжирование через OpenRouter (если задан ключ). → индексы по убыванию."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        import urllib.request
        prompt = ("Оцени сегменты речи для вирального Reels по силе хука, конфликту, "
                  "цитируемости, эмоции и пользе. Верни JSON-массив индексов от лучшего к худшему.\n" +
                  "\n".join(f"{i}: {t}" for i, t in enumerate(segments)))
        body = json.dumps({"model": "meta-llama/llama-3.1-8b-instruct",
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=40))
        txt = r["choices"][0]["message"]["content"]
        return json.loads(re.search(r"\[.*\]", txt, re.S).group(0))
    except Exception as e:
        sys.stderr.write(f"[select_moments] LLM недоступен ({str(e)[:80]}) — эвристика\n")
        return None


if __name__ == "__main__":
    demo = [
        "Знаешь главную ошибку в продажах?", "Почему клиент отваливается на одной фразе.",
        "Ну вот как бы это работает.", "Секрет в том что менеджер отвечает зависит.",
        "И теряет 3 миллиона тенге за месяц.",
    ]
    for t in demo:
        print(f"  {seg_score(t):>3}  {t}")
