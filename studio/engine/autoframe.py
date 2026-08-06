#!/usr/bin/env python3
"""Автофрейминг по лицам (движок Talgat AI Video Studio).

Находит лицо в кадре (OpenCV YuNet) и кадрирует ролик в 9:16 так, чтобы лицо
было в кадре, а не обрезалось центром. Работает офлайн (модель engine/yunet.onnx).

    python3 studio/engine/autoframe.py in.mp4 out.mp4     # реврейм в 1080x1920 по лицу
    python3 studio/engine/autoframe.py in.mp4             # только crops.json (доля центра лица)

Мягкий откат: лицо не найдено → центр кадра.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "yunet.onnx")


def face_center_fraction(path: str, sample_every: float = 0.4) -> float:
    """Медианная горизонтальная позиция лица (доля ширины 0..1). 0.5 — если лиц нет."""
    import cv2
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 0.5
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    det = cv2.FaceDetectorYN_create(MODEL, "", (w, h), score_threshold=0.6)
    det.setInputSize((w, h))
    step = max(1, int(fps * sample_every))
    centers, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            try:
                _, faces = det.detect(frame)
            except Exception:
                faces = None
            if faces is not None and len(faces):
                # крупнейшее лицо в кадре
                f = max(faces, key=lambda r: r[2] * r[3])
                centers.append((f[0] + f[2] / 2) / w)
        idx += 1
    cap.release()
    if not centers:
        return 0.5
    centers.sort()
    return float(centers[len(centers) // 2])


def autoframe(inp: str, out: str | None = None, W: int = 1080, H: int = 1920):
    fx = face_center_fraction(inp)
    crops = {"src": os.path.basename(inp), "face_cx": round(fx, 3),
             "note": "доля ширины, где центр лица (0.5 = центр)"}
    with open(os.path.splitext(inp)[0] + ".crops.json", "w", encoding="utf-8") as f:
        json.dump(crops, f, ensure_ascii=False)
    if out:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H}:x='min(max(iw*{fx:.3f}-{W}/2\\,0)\\,iw-{W})':y=(ih-{H})/2,setsar=1")
        subprocess.run([ff, "-y", "-i", inp, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", out],
                       check=True, capture_output=True)
    return fx


def autoframe_dynamic(inp: str, out: str, W: int = 1080, H: int = 1920,
                      sample_every: int = 3, ema: float = 0.14):
    """Динамический реврейм: камера ведёт за лицом покадрово со сглаживанием (EMA).
    Кроп 9:16 следует за спикером, а не статичный центр. Звук исходника сохраняется."""
    import cv2
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cap = cv2.VideoCapture(inp)
    if not cap.isOpened():
        return autoframe(inp, out, W, H)  # откат на статичный
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    sw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    sh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    det = cv2.FaceDetectorYN_create(MODEL, "", (sw, sh), score_threshold=0.6)
    det.setInputSize((sw, sh))
    scaled_w = max(W, int(round(sw * H / sh)))   # вписываем по высоте
    cx = scaled_w / 2                            # текущий (сглаженный) центр кропа, в px масштабир. кадра
    proc = subprocess.Popen(
        [ff, "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-",
         "-i", inp, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
         "-movflags", "+faststart", out],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    i = 0
    target = cx
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % sample_every == 0:
            try:
                _, faces = det.detect(frame)
            except Exception:
                faces = None
            if faces is not None and len(faces):
                f = max(faces, key=lambda r: r[2] * r[3])
                fcx = (f[0] + f[2] / 2) * (H / sh)   # центр лица в масштабир. кадре
                target = fcx
        cx += (target - cx) * ema                   # сглаживание
        big = cv2.resize(frame, (scaled_w, H))
        x = int(min(max(cx - W / 2, 0), scaled_w - W))
        crop = big[0:H, x:x + W]
        try:
            proc.stdin.write(crop.tobytes())
        except BrokenPipeError:
            break
        i += 1
    cap.release()
    try:
        proc.stdin.close()
    except Exception:
        pass
    proc.wait()
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: autoframe.py in.mp4 [out.mp4] [--dynamic]")
        raise SystemExit(1)
    if "--dynamic" in sys.argv:
        o = [a for a in sys.argv[2:] if not a.startswith("--")][0]
        autoframe_dynamic(sys.argv[1], o)
        print("динамический реврейм →", o)
        raise SystemExit(0)
    fx = autoframe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"лицо по x = {fx:.3f} (0.5 = центр)" + (f" → {sys.argv[2]}" if len(sys.argv) > 2 else ""))
