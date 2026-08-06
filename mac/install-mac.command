#!/bin/bash
# ФАБРИКА REELS — установка на Mac одним двойным кликом.
# Требуется: «Google Drive для компьютера» (папки Диска станут локальными).
# После установки Mac сам следит за «00 Исходники» и рендерит в «01 Готовые».
set -e
cd "$(dirname "$0")/.."
REPO="$(pwd)"
echo "▶ Reels-фабрика — установка на этот Mac"
echo "  папка проекта: $REPO"

# 1) найти локальные папки Google Drive
BASE=""
for d in "$HOME/Library/CloudStorage"/GoogleDrive-*/My\ Drive "$HOME/Google Drive/My Drive" "$HOME/Google Drive"; do
  [ -d "$d" ] && { BASE="$d"; break; }
done
if [ -z "$BASE" ]; then
  echo "✗ Не найден «Google Drive для компьютера»."
  echo "  Поставь: https://www.google.com/drive/download/ , войди в свой Google, дождись синка — и запусти этот файл снова."
  read -n1 -r -p "Нажми любую клавишу…"; exit 1
fi
IN="$BASE/АСП — Сериал 200 компаний/00 Исходники (съёмки)"
OUT="$BASE/АСП — Сериал 200 компаний/01 Готовые ролики"
echo "  вход:  $IN"
echo "  выход: $OUT"
if [ ! -d "$IN" ]; then
  echo "✗ Папка входа ещё не синхронизирована. Открой Google Drive, дождись синка папки и запусти снова."
  read -n1 -r -p "Нажми любую клавишу…"; exit 1
fi
mkdir -p "$OUT"

# 2) Python + зависимости
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "✗ Нет python3. Поставь https://www.python.org/downloads/macos/ и запусти снова."
  read -n1 -r -p "Нажми любую клавишу…"; exit 1
fi
echo "▶ ставлю зависимости…"
"$PY" -m pip install --user -q -r "$REPO/montage/requirements.txt"
"$PY" -m pip install --user -q -r "$REPO/montage/requirements-subs.txt" || echo "  (субтитры по речи доустановятся позже)"
"$PY" -c "import imageio_ffmpeg; print('  ffmpeg:', imageio_ffmpeg.get_ffmpeg_exe())"

# 3) автозапуск (LaunchAgent — стартует сам при входе в систему)
mkdir -p "$HOME/Library/LaunchAgents"
PLIST="$HOME/Library/LaunchAgents/top.systemop.reels.plist"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>top.systemop.reels</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string>
    <string>$REPO/montage/autorun.py</string>
    <string>--watch</string><string>$IN</string>
    <string>--out</string><string>$OUT</string>
    <string>--interval</string><string>30</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/reels-factory.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/reels-factory.log</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "✅ Готово. Фабрика запущена и стартует сама при входе в систему."
echo "   Залей ролик с телефона в Drive «00 Исходники» → через ~30 сек готовый появится в «01 Готовые» → синхронизируется на телефон."
echo "   Логи: ~/Library/Logs/reels-factory.log"
echo "   Остановить: launchctl unload \"$PLIST\""
read -n1 -r -p "Нажми любую клавишу, чтобы закрыть…"
