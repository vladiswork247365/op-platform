#!/usr/bin/env python3
"""ElevenLabs: озвучка текста голосом (в т.ч. КЛОНОМ голоса автора) + тайминги слов.

Зачем: снимаешь ролик молча / без чистого звука, даёшь СКРИПТ (текстом или голосовым
ТЗ) — а система проговаривает его твоим клон-голосом, и звук + субтитры ложатся сами
по таймингам. Читать по губам нельзя, поэтому нужен текст скрипта.

Что умеет:
  • tts_timed(text, out_mp3, voice_id) → (mp3, [{start,end,word}]) — озвучка + тайминги
    для авто-субтитров (эндпоинт /with-timestamps).
  • tts(text, out_mp3, voice_id) → mp3 — просто озвучка.
  • voices() → список доступных голосов (id + имя).
  • clone(name, [samples…]) → voice_id — создать клон голоса из образцов (один раз).

Ключ: ELEVEN_KEY (или ELEVEN_API_KEY) в montage/.env. Голос по умолчанию: ELEVEN_VOICE_ID.
Без ключа всё мягко выключено (функции возвращают None). Только стандартная библиотека.
"""
from __future__ import annotations
import base64
import json
import os
import sys
import urllib.request
import uuid

API = "https://api.elevenlabs.io"


def _load_env():
    """Подхватить montage/.env при запуске напрямую (бот грузит .env сам, но CLI — нет)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, ".env"), os.path.join(os.path.dirname(here), ".env")):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()

MODEL = os.environ.get("ELEVEN_MODEL", "eleven_multilingual_v2")   # мультиязычный — есть русский


def api_key(explicit: str | None = None) -> str | None:
    return explicit or os.environ.get("ELEVEN_KEY") or os.environ.get("ELEVEN_API_KEY")


def have_key() -> bool:
    return bool(api_key())


def default_voice() -> str | None:
    return os.environ.get("ELEVEN_VOICE_ID")


def _req(path, data=None, headers=None, method=None, timeout=120):
    url = API + path
    h = {"xi-api-key": api_key()}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def voices():
    """Список голосов аккаунта → [{'voice_id','name'}]. None без ключа/при ошибке."""
    if not have_key():
        return None
    try:
        r = json.load(_req("/v1/voices", headers={"Accept": "application/json"}))
        return [{"voice_id": v["voice_id"], "name": v.get("name", "")} for v in r.get("voices", [])]
    except Exception as e:
        sys.stderr.write(f"[eleven.voices] {type(e).__name__}: {str(e)[:100]}\n")
        return None


def _voice_settings(override: dict | None = None):
    s = {"stability": float(os.environ.get("ELEVEN_STABILITY", "0.45")),
         "similarity_boost": float(os.environ.get("ELEVEN_SIMILARITY", "0.85")),
         "style": float(os.environ.get("ELEVEN_STYLE", "0.35")),
         "use_speaker_boost": True}
    if override:  # режиссёр (Opus) задаёт подачу: stability/style/speed
        for k in ("stability", "style"):
            if override.get(k) is not None:
                s[k] = float(override[k])
        if override.get("speed") is not None:
            s["speed"] = float(override["speed"])
    return s


def tts(text: str, out_mp3: str, voice_id: str | None = None, timeout: int = 120):
    """Озвучить text голосом voice_id → сохранить mp3. Вернуть путь или None."""
    if not have_key():
        return None
    vid = voice_id or default_voice()
    if not vid:
        sys.stderr.write("[eleven.tts] нет voice_id (ELEVEN_VOICE_ID)\n")
        return None
    body = json.dumps({"text": text, "model_id": MODEL,
                       "voice_settings": _voice_settings()}).encode("utf-8")
    try:
        resp = _req(f"/v1/text-to-speech/{vid}", data=body,
                    headers={"Content-Type": "application/json", "Accept": "audio/mpeg"},
                    method="POST", timeout=timeout)
        with open(out_mp3, "wb") as f:
            f.write(resp.read())
        return out_mp3
    except Exception as e:
        sys.stderr.write(f"[eleven.tts] {type(e).__name__}: {str(e)[:120]}\n")
        return None


def _chars_to_words(chars, starts, ends):
    """Посимвольный alignment → слова с таймингами (для субтитров)."""
    words, cur, cs, ce = [], "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"start": round(cs, 3), "end": round(ce, 3), "word": cur})
                cur, cs, ce = "", None, None
        else:
            if not cur:
                cs = s
            cur += ch
            ce = e
    if cur:
        words.append({"start": round(cs, 3), "end": round(ce, 3), "word": cur})
    return words


def tts_timed(text: str, out_mp3: str, voice_id: str | None = None, timeout: int = 120,
              settings: dict | None = None):
    """Озвучка + тайминги слов. → (mp3_path, [{start,end,word}]) или None.

    settings — подача голоса от режиссёра (stability/style/speed).
    Использует /with-timestamps: аудио + посимвольный alignment → слова для субтитров.
    """
    if not have_key():
        return None
    vid = voice_id or default_voice()
    if not vid:
        sys.stderr.write("[eleven.tts_timed] нет voice_id (ELEVEN_VOICE_ID)\n")
        return None
    body = json.dumps({"text": text, "model_id": MODEL,
                       "voice_settings": _voice_settings(settings)}).encode("utf-8")
    try:
        resp = _req(f"/v1/text-to-speech/{vid}/with-timestamps", data=body,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    method="POST", timeout=timeout)
        data = json.load(resp)
        audio = base64.b64decode(data["audio_base64"])
        with open(out_mp3, "wb") as f:
            f.write(audio)
        al = data.get("alignment") or data.get("normalized_alignment") or {}
        words = _chars_to_words(al.get("characters", []),
                                al.get("character_start_times_seconds", []),
                                al.get("character_end_times_seconds", []))
        return out_mp3, words
    except Exception as e:
        sys.stderr.write(f"[eleven.tts_timed] {type(e).__name__}: {str(e)[:120]}\n")
        return None


def _multipart(fields, files):
    """Собрать multipart/form-data вручную (без внешних пакетов)."""
    boundary = "----op" + uuid.uuid4().hex
    nl = b"\r\n"
    buf = bytearray()
    for k, v in fields.items():
        buf += b"--" + boundary.encode() + nl
        buf += f'Content-Disposition: form-data; name="{k}"'.encode() + nl + nl
        buf += str(v).encode("utf-8") + nl
    for k, path in files:
        fn = os.path.basename(path)
        buf += b"--" + boundary.encode() + nl
        buf += f'Content-Disposition: form-data; name="{k}"; filename="{fn}"'.encode() + nl
        buf += b"Content-Type: application/octet-stream" + nl + nl
        with open(path, "rb") as f:
            buf += f.read()
        buf += nl
    buf += b"--" + boundary.encode() + b"--" + nl
    return bytes(buf), f"multipart/form-data; boundary={boundary}"


def clone(name: str, samples: list[str], description: str = "", timeout: int = 300):
    """Создать клон голоса из образцов (1–3 чистых записи по 1–2 мин). → voice_id | None."""
    if not have_key():
        return None
    files = [("files", p) for p in samples if os.path.exists(p)]
    if not files:
        sys.stderr.write("[eleven.clone] нет файлов-образцов\n")
        return None
    fields = {"name": name}
    if description:
        fields["description"] = description
    data, ctype = _multipart(fields, files)
    try:
        resp = _req("/v1/voices/add", data=data,
                    headers={"Content-Type": ctype, "Accept": "application/json"},
                    method="POST", timeout=timeout)
        return json.load(resp).get("voice_id")
    except Exception as e:
        sys.stderr.write(f"[eleven.clone] {type(e).__name__}: {str(e)[:150]}\n")
        return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="ElevenLabs: озвучка / клон голоса")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("voices", help="список голосов аккаунта")
    p_say = sub.add_parser("say", help="озвучить текст (+ тайминги слов)")
    p_say.add_argument("text")
    p_say.add_argument("--voice", default=None)
    p_say.add_argument("--out", default="voice.mp3")
    p_cl = sub.add_parser("clone", help="создать клон голоса из образцов")
    p_cl.add_argument("name")
    p_cl.add_argument("samples", nargs="+")
    a = ap.parse_args()
    if a.cmd == "voices":
        vs = voices()
        print("нет ключа/ошибка" if vs is None else json.dumps(vs, ensure_ascii=False, indent=2))
    elif a.cmd == "say":
        res = tts_timed(a.text, a.out, a.voice)
        if not res:
            print("не удалось (нет ключа/voice_id/сети?)")
        else:
            mp3, words = res
            print(f"✅ {mp3}  |  слов с таймингами: {len(words)}")
            print(json.dumps(words[:12], ensure_ascii=False))
    elif a.cmd == "clone":
        vid = clone(a.name, a.samples)
        print(f"voice_id: {vid}" if vid else "не удалось создать клон")
    else:
        ap.print_help()
