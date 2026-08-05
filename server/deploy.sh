#!/usr/bin/env bash
# Разворачивает Reels-фабрику на сервере. Запусти из папки server/ на VPS с Docker:
#   bash deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p config data

# один раз: авторизация Google Drive (remote ДОЛЖЕН называться gdrive)
if [ ! -f config/rclone.conf ]; then
  echo "▶ Нет config/rclone.conf. Запускаю одноразовую авторизацию Google Drive."
  echo "  В мастере: n → имя gdrive → drive → scope 1 → авторизуйся в свой Google."
  docker run -it --rm -v "$PWD/config:/config" -e RCLONE_CONFIG=/config/rclone.conf \
      rclone/rclone config
fi

echo "▶ Сборка и запуск (первый билд качает whisper-модель — пару минут)…"
docker compose up -d --build
echo "▶ Готово. Логи:"
docker compose logs -f
