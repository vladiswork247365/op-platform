"""Telegram Bot API — тупая труба ввода/вывода. Никакой логики.

Вход разбирается в роутере. Здесь — только скачивание сырья и отправка результата.
Для локального прогона без токена (DEV_FAKE_SOURCE) сырьё генерируется ffmpeg-ом.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import httpx

from .config import settings

API = "https://api.telegram.org"


def _token() -> str:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    return settings.TELEGRAM_BOT_TOKEN


def download_source(source_ref: str) -> str:
    """Скачивает сырьё в локальный временный файл, возвращает путь.

    source_ref может быть:
      - http(s) URL           → качаем напрямую;
      - telegram file_id       → getFile + download (нужен токен);
      - (dev) без токена       → генерируем тестовый ролик ffmpeg-ом.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="cf_src_"))
    dest = tmp_dir / "source.mp4"

    if source_ref.startswith(("http://", "https://")):
        with httpx.stream("GET", source_ref, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return str(dest)

    if settings.TELEGRAM_BOT_TOKEN:
        with httpx.Client(timeout=60) as c:
            meta = c.get(f"{API}/bot{_token()}/getFile", params={"file_id": source_ref})
            meta.raise_for_status()
            file_path = meta.json()["result"]["file_path"]
            with c.stream("GET", f"{API}/file/bot{_token()}/{file_path}") as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        return str(dest)

    if settings.DEV_FAKE_SOURCE:
        # dev-шим: без токена генерируем 5-сек ролик, чтобы прогнать конвейер.
        _ffmpeg_testsrc(dest, seconds=5)
        return str(dest)

    raise RuntimeError(f"Не могу скачать сырьё: {source_ref!r} (нет токена и не URL)")


def send_message(chat_id: int, text: str) -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        print(f"[telegram dry] → chat {chat_id}: {text}")
        return
    with httpx.Client(timeout=30) as c:
        c.post(f"{API}/bot{_token()}/sendMessage", json={"chat_id": chat_id, "text": text})


def send_video(chat_id: int, video_path: str, caption: str = "") -> bool:
    """Пытается отправить видеофайл. Возвращает True при успехе.

    Cloud Bot API ограничивает отправку ~50 МБ — при отказе вызывающий код
    падает на превью+ссылку (см. воркер, шаг delivering)."""
    if not settings.TELEGRAM_BOT_TOKEN:
        print(f"[telegram dry] → chat {chat_id}: video {video_path} | {caption}")
        return True
    try:
        with httpx.Client(timeout=300) as c, open(video_path, "rb") as f:
            resp = c.post(
                f"{API}/bot{_token()}/sendVideo",
                data={"chat_id": chat_id, "caption": caption},
                files={"video": f},
            )
        return resp.status_code == 200 and resp.json().get("ok", False)
    except Exception as e:  # сеть/размер — не роняем воркер, откатываемся на ссылку
        print(f"[telegram] sendVideo failed: {e}")
        return False


def _ffmpeg_testsrc(dest: Path, seconds: int = 5) -> None:
    subprocess.run(
        [
            settings.FFMPEG_BIN, "-y", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=640x360:rate=25",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(dest),
        ],
        check=True, capture_output=True,
    )
