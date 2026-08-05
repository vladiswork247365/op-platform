#!/usr/bin/env bash
# Развёртывание авто-обработчика на чистом Ubuntu VPS БЕЗ Docker.
# Запусти на сервере:  bash server/setup-vps.sh
set -euo pipefail

echo "▶ ставлю зависимости…"
sudo apt-get update
sudo apt-get install -y python3-pip fonts-dejavu-core curl unzip ca-certificates
curl -fsSL https://rclone.org/install.sh | sudo bash

pip3 install --user -r montage/requirements.txt
python3 -c "import imageio_ffmpeg; print('ffmpeg:', imageio_ffmpeg.get_ffmpeg_exe())"

cat <<'NOTE'

✅ Зависимости готовы. Дальше один раз авторизуй Google Drive:

    rclone config
      n  → имя: gdrive
      Storage: drive
      (client_id/secret можно пустые)
      scope: 1 (полный доступ)
      Use auto config? Если сервер без браузера — N, и выполни на своём ноутбуке:
          rclone authorize "drive"
      затем вставь полученный токен в консоль сервера.

Затем запусти обработчик (ID папок уже подставлены):

    IN_ID=1QuNqWxBNxhrhvetf13cJLoTQLLHTLbGw \
    OUT_ID=1PlwYzMJG0CYJxz-0Dkfn9Lrp4K2Ntomc \
    bash server/entrypoint.sh

Чтобы работал 24/7 — заверни в systemd-сервис (пример в server/README.md).
NOTE
