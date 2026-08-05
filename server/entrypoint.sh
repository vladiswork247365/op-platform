#!/usr/bin/env bash
# Цикл авто-обработки: Drive → рендер → Drive.
# ENV: IN_ID / OUT_ID — ID папок Диска «00 Исходники» и «01 Готовые».
#      INTERVAL — период синхронизации, сек (по умолчанию 60).
set -euo pipefail

: "${IN_ID:?нужен ID папки 00 Исходники}"
: "${OUT_ID:?нужен ID папки 01 Готовые}"
INTERVAL="${INTERVAL:-60}"
REMOTE="${REMOTE:-gdrive}"

mkdir -p /data/sources /data/out
echo "▶ обработчик запущен. IN=$IN_ID OUT=$OUT_ID interval=${INTERVAL}s"

# движок-вотчер: следит за /data/sources, рендерит новое в /data/out (дедуп внутри)
python3 /app/montage/autorun.py --watch /data/sources --out /data/out --interval 15 &

# цикл синхронизации с Google Drive
while true; do
  rclone copy "${REMOTE},root_folder_id=${IN_ID}:" /data/sources \
      --transfers 4 --drive-acknowledge-abuse -q || echo "⚠ pull не удался, повтор позже"
  rclone copy /data/out "${REMOTE},root_folder_id=${OUT_ID}:" \
      --transfers 4 -q || echo "⚠ push не удался, повтор позже"
  sleep "$INTERVAL"
done
