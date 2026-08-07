#!/bin/bash
# ТЕЛЕГРАМ-БОТ ПРИЁМА РОЛИКОВ (до 2 ГБ) — запуск двойным кликом.
# Спросит ключи один раз (сохранит в montage/.env), поставит зависимости и запустит бота.
cd "$(dirname "$0")/.."
REPO="$(pwd)"
clear
echo "▶ Reels-бот в Telegram (приём роликов до 2 ГБ → монтаж → готовый Reel)"
echo "  проект: $REPO"
echo

# 0) python3 + ffmpeg
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ Нет python3. Выполни в Терминале: xcode-select --install — и запусти снова."
  read -n1 -r -p "Нажми любую клавишу…"; exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠️ Не найден ffmpeg (движок монтажа). Поставь его: brew install ffmpeg"
  echo "   (или запусти mac/install-mac.command — он ставит всё для фабрики)."
  read -r -p "Продолжить всё равно? [Enter — да / n — выйти] " a; [ "$a" = "n" ] && exit 1
fi

# 1) обновить проект (если git-клон)
[ -d .git ] && { echo "▶ Обновляю проект…"; git pull --ff-only 2>/dev/null || true; echo; }

# 2) ключи Telegram
ENV="montage/.env"
ask() { # ask VAR "подсказка"
  local var="$1" hint="$2" cur
  cur=$(grep -E "^$var=" "$ENV" 2>/dev/null | cut -d= -f2-)
  if [ -n "$cur" ]; then return; fi
  read -r -p "  $hint: " val
  [ -z "$val" ] && { echo "  ✗ пусто — прерываю."; exit 1; }
  mkdir -p montage; echo "$var=$val" >> "$ENV"
}
if ! grep -q '^TG_BOT_TOKEN=' "$ENV" 2>/dev/null || ! grep -q '^TG_API_ID=' "$ENV" 2>/dev/null; then
  echo "▶ Нужны ключи Telegram (как получить — montage/TG-SETUP.md):"
  ask TG_API_ID    "TG_API_ID (число с my.telegram.org)"
  ask TG_API_HASH  "TG_API_HASH (строка с my.telegram.org)"
  ask TG_BOT_TOKEN "TG_BOT_TOKEN (от @BotFather)"
  chmod 600 "$ENV"
  echo "  ключи сохранены в $ENV (в git не попадают)"
fi
echo

# 3) зависимости бота
echo "▶ Проверяю зависимости (pyrogram)…"
python3 -c "import pyrogram, tgcrypto" 2>/dev/null || pip3 install -q -r montage/requirements-tg.txt || {
  echo "✗ Не удалось поставить pyrogram. Выполни вручную: pip3 install pyrogram tgcrypto"; read -n1 -r -p "…"; exit 1; }

# 4) запуск
echo
echo "▶ Запускаю бота. Открой его в Telegram, команда /start, и кидай видео."
echo "  Чтобы остановить — закрой это окно или Ctrl+C."
echo "──────────────────────────────────────────────────────────────────────"
python3 montage/tg_bot.py
echo "──────────────────────────────────────────────────────────────────────"
read -n1 -r -p "Бот остановлен. Нажми любую клавишу, чтобы закрыть…"
