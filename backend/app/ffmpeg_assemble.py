"""FFmpeg-сборка (шаг assembling воркера).

Панель правит рецепт, а не пиксели: собираем мастер по пресету — формат, сабы,
битрейт. Никакого таймлайна. На вход — выход инструмента, на выход — мастер+превью.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .config import settings

# соотношение сторон → целевой кадр (по большей стороне 1080)
_DIMS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def _escape_drawtext(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")


def assemble_master(input_path: str, snapshot: dict) -> tuple[str, str]:
    """Собирает мастер и превью по замороженному пресету.

    Возвращает (master_path, preview_path). Файлы во временной папке —
    вызывающий воркер заливает их в R2.
    """
    fmt = snapshot.get("format", "9:16")
    w, h = _DIMS.get(fmt, _DIMS["9:16"])
    out_dir = Path(tempfile.mkdtemp(prefix="cf_out_"))
    master = out_dir / "master.mp4"
    preview = out_dir / "preview.jpg"

    # scale+pad до целевого формата, не искажая картинку
    base_vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
    )

    # опциональные вшитые субтитры (простой drawtext по стилю из пресета)
    subs_vf = ""
    subs = snapshot.get("subtitle_style") or {}
    caption = (subs.get("text") or snapshot.get("name") or "").strip()
    if caption and subs.get("enabled", True) and subs.get("style") != "off":
        color = subs.get("color", "white")
        pos = subs.get("position", "bottom")
        y = {"top": "40", "center": "(h-text_h)/2", "bottom": "h-text_h-60"}.get(pos, "h-text_h-60")
        fontsize = int(subs.get("fontsize", 42))
        subs_vf = (
            f",drawtext=text='{_escape_drawtext(caption)}':fontcolor={color}:fontsize={fontsize}"
            f":x=(w-text_w)/2:y={y}:box=1:boxcolor=black@0.45:boxborderw=14"
        )

    length = snapshot.get("length")

    def _build(vf: str) -> list[str]:
        cmd = [
            settings.FFMPEG_BIN, "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "4M", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        ]
        if length:
            cmd += ["-t", str(int(length))]
        cmd.append(str(master))
        return cmd

    # сабы — приятное дополнение: если drawtext/шрифт недоступен, не роняем мастер
    try:
        subprocess.run(_build(base_vf + subs_vf), check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        if not subs_vf:
            raise
        print(f"[ffmpeg] сабы пропущены (drawtext недоступен): {e.stderr.decode()[-200:]}")
        subprocess.run(_build(base_vf), check=True, capture_output=True)

    # превью — кадр из середины
    subprocess.run(
        [settings.FFMPEG_BIN, "-y", "-i", str(master), "-ss", "1", "-frames:v", "1", "-q:v", "3", str(preview)],
        check=True, capture_output=True,
    )
    return str(master), str(preview)
