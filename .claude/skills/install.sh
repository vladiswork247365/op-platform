#!/usr/bin/env bash
# Установка пака video-* в пользовательские скиллы Claude Code (~/.claude),
# чтобы категория была доступна во всех проектах, а не только в этом репозитории.
set -euo pipefail

SRC_SKILLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(dirname "$SRC_SKILLS")"
DST_SKILLS="$HOME/.claude/skills"
DST_CMDS="$HOME/.claude/commands/video"

mkdir -p "$DST_SKILLS" "$DST_CMDS"

echo "→ Скиллы в $DST_SKILLS"
for d in "$SRC_SKILLS"/video-*/; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  rm -rf "${DST_SKILLS:?}/$name"
  cp -R "$d" "$DST_SKILLS/$name"
  echo "   ✓ $name"
done

echo "→ Команды в $DST_CMDS"
cp -f "$SRC_ROOT"/commands/video/*.md "$DST_CMDS"/
echo "   ✓ $(ls -1 "$DST_CMDS"/*.md | wc -l | tr -d ' ') шт."

cp -f "$SRC_SKILLS/README.md" "$DST_SKILLS/VIDEO-README.md"

echo
echo "Готово. Перезапустите Claude Code, чтобы он подхватил новые скиллы."
echo "Проверка: /video:status"
echo
echo "Что ещё нужно для полноценной работы:"
if command -v ffmpeg >/dev/null 2>&1; then
  echo "  ✓ ffmpeg: $(ffmpeg -version | head -1 | cut -d' ' -f1-3)"
else
  echo "  ✗ ffmpeg НЕ УСТАНОВЛЕН → brew install ffmpeg | sudo apt install ffmpeg | winget install ffmpeg"
fi

if command -v whisper-cli >/dev/null 2>&1 || command -v whisper >/dev/null 2>&1; then
  echo "  ✓ whisper найден"
else
  echo "  ○ whisper не установлен (нужен для бесплатных субтитров) → brew install whisper-cpp | pip install faster-whisper"
fi
