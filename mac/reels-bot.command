#!/bin/bash
# ТЕЛЕГРАМ-БОТ ПРИЁМА РОЛИКОВ (до 2 ГБ) — запуск двойным кликом.
# Спросит ключи один раз (сохранит в montage/.env), поставит зависимости и запустит бота.
cd "$(dirname "$0")/.."
REPO="$(pwd)"
clear
echo "▶ Reels-бот в Telegram (приём роликов до 2 ГБ → монтаж → готовый Reel)"
echo "  проект: $REPO"
echo

# 0) python3 (ffmpeg отдельно НЕ нужен — идёт в пакете imageio-ffmpeg)
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ Нет python3. Выполни в Терминале: xcode-select --install — и запусти снова."
  read -n1 -r -p "Нажми любую клавишу…"; exit 1
fi

# 1) авто-обновление кода до последней версии
if [ -d .git ]; then
  echo "▶ Обновляю проект (git)…"; git pull --ff-only 2>/dev/null || true; echo
elif command -v curl >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1; then
  # проект скачан ZIP-ом (без git): тянем свежий код из GitHub и кладём поверх.
  # .env с ключами и папку fonts НЕ трогаем — обновляется только код (*.py, launcher'ы).
  echo "▶ Обновляю код до последней версии…"
  TMPZIP="$(mktemp -t opreels 2>/dev/null || echo /tmp/opreels).zip"
  if curl -fsSL "https://github.com/vladiswork247365/op-platform/archive/refs/heads/main.zip" -o "$TMPZIP" 2>/dev/null; then
    TMPD="$(mktemp -d)"
    if unzip -oq "$TMPZIP" -d "$TMPD" 2>/dev/null; then
      SRC="$TMPD/op-platform-main"
      if [ -d "$SRC/montage" ]; then
        cp -f "$SRC"/montage/*.py montage/ 2>/dev/null
        cp -f "$SRC"/montage/requirements*.txt montage/ 2>/dev/null
        cp -f "$SRC"/montage/stress_dict.json montage/ 2>/dev/null      # словарь ударений
        # твои поправки ударений (stress_overrides.json) и данные (reels.json) НЕ трогаем
        [ -f montage/stress_overrides.json ] || cp -f "$SRC"/montage/stress_overrides.json montage/ 2>/dev/null
        mkdir -p montage/assets && cp -Rf "$SRC"/montage/assets/. montage/assets/ 2>/dev/null  # музыка из коробки
      fi
      [ -d "$SRC/factory/prompts" ] && { mkdir -p factory/prompts; cp -f "$SRC"/factory/prompts/*.md factory/prompts/ 2>/dev/null; }
      [ -d "$SRC/mac" ] && cp -f "$SRC"/mac/*.command mac/ 2>/dev/null
      echo "  ✓ код+музыка+словарь ударений свежие (ключи .env, поправки и шрифты сохранены)"
    fi
    rm -rf "$TMPD"
  else
    echo "  ⚠️ не смог обновиться (нет сети/VPN?) — запускаю текущую версию"
  fi
  rm -f "$TMPZIP"
  echo
fi

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

# 3) зависимости: бот (pyrogram) + движок монтажа (Pillow/ffmpeg-бинарник и т.д.)
echo "▶ Ставлю зависимости (бот + движок монтажа)… может занять минуту в первый раз"
python3 -c "import pyrogram, tgcrypto, cv2" 2>/dev/null || pip3 install -q -r montage/requirements-tg.txt || {
  echo "✗ Не удалось поставить зависимости бота. Выполни: pip3 install -r montage/requirements-tg.txt"; read -n1 -r -p "…"; exit 1; }
python3 -c "import PIL, imageio_ffmpeg, numpy" 2>/dev/null || pip3 install -q -r montage/requirements.txt || {
  echo "✗ Не удалось поставить движок монтажа. Выполни: pip3 install -r montage/requirements.txt"; read -n1 -r -p "…"; exit 1; }
# распознавание речи → пословные субтитры (обязательно для стиля с субтитрами)
python3 -c "import faster_whisper" 2>/dev/null || {
  echo "▶ Ставлю распознавание речи (faster-whisper) — субтитры по словам…"
  pip3 install -q faster-whisper || echo "⚠️ faster-whisper не встал — субтитры по речи будут недоступны (остальное работает)"; }
# премиум-шрифт субтитров (Montserrat ExtraBold) — чтобы не «колхозный» вид
mkdir -p montage/fonts
[ -f montage/fonts/Montserrat-ExtraBold.ttf ] || {
  echo "▶ Скачиваю шрифт Montserrat…"
  curl -fsSL "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-ExtraBold.ttf" \
    -o montage/fonts/Montserrat-ExtraBold.ttf || echo "⚠️ шрифт не скачался — будет системный"; }

# 4) запуск
echo
echo "▶ Запускаю бота. Открой его в Telegram, команда /start, и кидай видео."
echo "  Чтобы остановить — закрой это окно или Ctrl+C."
echo "──────────────────────────────────────────────────────────────────────"
python3 montage/tg_bot.py
echo "──────────────────────────────────────────────────────────────────────"
read -n1 -r -p "Бот остановлен. Нажми любую клавишу, чтобы закрыть…"
