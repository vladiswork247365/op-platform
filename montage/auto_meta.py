#!/usr/bin/env python3
"""Авто-хэштеги + описание под ролик (охват / дискаверабилити — рычаг к просмотрам).

Смешивает нишевые, средние и широкие теги + ключевые слова из речи. Эвристика
работает офлайн; при OPENROUTER_API_KEY описание/теги уточняет LLM.
"""
from __future__ import annotations
import os
import re
import sys

# теги по нише Влада (системные продажи / ОП / РОП) — от узких к широким
NICHE = ["#отделпродаж", "#системныепродажи", "#роп", "#скриптыпродаж", "#окк",
         "#менеджерпопродажам", "#b2bпродажи", "#конверсия", "#возражения"]
MID = ["#бизнес", "#предприниматель", "#продажи", "#маркетинг", "#управление", "#малыйбизнес"]
BROAD = ["#бизнесидеи", "#деньги", "#мотивация", "#успех", "#саморазвитие"]
STOP = set("и в во не что он на я с со как а то все она так его но да ты к у же за бы по "
           "это этот эта эти для мы вы их чем был была что-то очень".split())


def keywords(text, top=4):
    freq = {}
    for w in re.findall(r"[а-яёa-z]{5,}", (text or "").lower()):
        if w not in STOP:
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:top]]


def hashtags(text: str, n: int = 14):
    kw = ["#" + w for w in keywords(text, 4)]
    tags = []
    for src in (kw, NICHE, MID, BROAD):
        for t in src:
            if t not in tags:
                tags.append(t)
            if len(tags) >= n:
                return tags
    return tags[:n]


def caption(hook: str, text: str = "", cta: str = "Разбор — в профиле 👆"):
    tags = hashtags((hook + " " + text))
    lines = [hook.strip().rstrip(".") + ".", "", cta, "", " ".join(tags)]
    return "\n".join(lines)


def llm_caption(hook, text):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        import json, urllib.request
        prompt = (f"Хук ролика: «{hook}». Тема: {text[:400]}. Напиши цепляющее описание для "
                  f"Reels/TikTok (1-2 строки, без воды) + 12 релевантных хэштегов по продажам/бизнесу. "
                  f"Формат: описание, пустая строка, хэштеги в строку.")
        body = json.dumps({"model": "meta-llama/llama-3.1-8b-instruct",
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=40))
        return r["choices"][0]["message"]["content"].strip()
    except Exception as e:
        sys.stderr.write(f"[auto_meta] LLM недоступен ({str(e)[:70]}) — эвристика\n")
        return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Авто-хэштеги + описание")
    ap.add_argument("hook")
    ap.add_argument("--text", default="")
    a = ap.parse_args()
    print(llm_caption(a.hook, a.text) or caption(a.hook, a.text))
