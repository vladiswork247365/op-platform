#!/bin/bash
# ВЫТАЩИТЬ ТЕКСТ ИЗ ВИДЕО — двойной клик.
# Перетаскиваешь видео в окно, Enter — получаешь полный текст речи + файл рядом (<видео>.txt).
cd "$(dirname "$0")/.."
clear
echo "📝 Извлечение текста из видео (речь → текст)"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ Нет python3. Выполни: xcode-select --install — и запусти снова."
  read -n1 -r -p "Нажми любую клавишу…"; exit 1
fi

# зависимости распознавания (в первый раз — поставит; модель скачается автоматически)
python3 -c "import faster_whisper, imageio_ffmpeg" 2>/dev/null || {
  echo "▶ Ставлю распознавание речи (один раз)…"
  pip3 install -q faster-whisper imageio-ffmpeg || {
    echo "✗ Не удалось поставить. Выполни: pip3 install faster-whisper imageio-ffmpeg"; read -n1 -r -p "…"; exit 1; }
}

echo "Перетащи сюда видео/аудио файл и нажми Enter"
echo "(или вставь путь к файлу):"
read -r -e RAW
# убрать кавычки/экранирование, которые появляются при перетаскивании
FILE=$(echo "$RAW" | sed "s/^['\"]//; s/['\"]$//; s/\\\\ / /g")
if [ ! -f "$FILE" ]; then
  echo "✗ Файл не найден: $FILE"; read -n1 -r -p "…"; exit 1
fi

echo
echo "▶ Распознаю речь… (первый раз дольше — качается модель)"
echo "──────────────────────────────────────────────────────────────────────"
python3 montage/transcribe.py --text "$FILE"
echo "──────────────────────────────────────────────────────────────────────"
# открыть готовый .txt в TextEdit
[ -f "$FILE.txt" ] && open "$FILE.txt" 2>/dev/null
echo
read -n1 -r -p "Готово. Нажми любую клавишу, чтобы закрыть…"
