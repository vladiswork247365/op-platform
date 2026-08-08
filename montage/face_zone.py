#!/usr/bin/env python3
"""Определение безопасной зоны для субтитров по лицу в кадре.

Семплит несколько кадров исходника, находит лицо (YuNet, модель уже в проекте:
studio/engine/yunet.onnx) и возвращает Y-центр для субтитров как долю высоты (0..1),
так чтобы блок субтитров НЕ перекрывал лицо: обычно под лицом, а если лицо низко —
над ним. Всё мягко деградирует: нет opencv / модели / лица → возвращает None
(тогда используется нижняя безопасная зона по умолчанию).
"""
from __future__ import annotations
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL = os.path.join(ROOT, "studio", "engine", "yunet.onnx")

_HALF = 0.06      # половина высоты блока субтитров (≈2 строки) в долях кадра
_MARGIN = 0.035   # зазор от лица
_UI_BOTTOM = 0.87  # ниже — зона кнопок платформы, туда не лезем
_UI_TOP = 0.12


def _face_box_fraction(video_path, samples=7):
    """Медианный бокс лица по нескольким кадрам → (top, bottom) в долях высоты. None если нет."""
    try:
        import cv2  # noqa
        import numpy as np
    except Exception:
        return None
    if not os.path.exists(MODEL) or not os.path.exists(video_path):
        return None
    cap = cv2.VideoCapture(video_path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if W <= 0 or H <= 0:
        cap.release()
        return None
    try:
        det = cv2.FaceDetectorYN.create(MODEL, "", (W, H), score_threshold=0.6)
    except Exception:
        cap.release()
        return None
    idxs = [int(n * k / (samples + 1)) for k in range(1, samples + 1)] if n > 0 else [0]
    tops, bots = [], []
    for fi in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        det.setInputSize((frame.shape[1], frame.shape[0]))
        try:
            _, faces = det.detect(frame)
        except Exception:
            continue
        if faces is None or len(faces) == 0:
            continue
        # берём самое крупное лицо в кадре
        f = max(faces, key=lambda r: float(r[2]) * float(r[3]))
        y, h = float(f[1]), float(f[3])
        tops.append(max(0.0, y / frame.shape[0]))
        bots.append(min(1.0, (y + h) / frame.shape[0]))
    cap.release()
    if not bots:
        return None
    tops.sort(); bots.sort()
    return tops[len(tops) // 2], bots[len(bots) // 2]


def subtitle_y_fraction(video_path):
    """Y-центр субтитров (доля высоты 0..1), не попадающий на лицо. None → дефолт."""
    box = _face_box_fraction(video_path)
    if not box:
        return None
    ft, fb = box
    below = fb + _MARGIN + _HALF          # разместить под лицом
    if below + _HALF <= _UI_BOTTOM:
        return round(min(below, 0.80), 3)
    above = ft - _MARGIN - _HALF          # лицо низко → над лицом
    if above - _HALF >= _UI_TOP:
        return round(max(above, 0.16), 3)
    return None                            # некуда — пусть решает дефолт


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python3 face_zone.py <video>")
    else:
        print("Y-доля субтитров:", subtitle_y_fraction(sys.argv[1]))
