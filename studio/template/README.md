# Remotion-шаблон (движок кинетик/караоке)

React-рендер для сложных сцен (караоке-сабы, кинетик-типографика) — как в
Talgat AI Video Studio. Дополняет ffmpeg-движок для случаев, где нужен код-моушн.

## Запуск
```bash
cd studio/template
npm install
npm run studio        # превью в браузере (remotion studio)
npm run render        # рендер KaraokeReel → out/reel.mp4
```
Chromium в среде уже есть (PLAYWRIGHT_BROWSERS_PATH) — Remotion его подхватит.

## Композиции (= стили)
- **KaraokeReel** (`src/KaraokeReel.tsx`) — сабы пословно с bounce-pop поверх видео;
  props: `videoSrc`, `music`, `words:[{start,end,word}]` (тайминги из transcribe.py).

## Дальше (допинать вместе)
Добавить композиции-стили из каталога: Vox-explainer, kinetic-editorial,
Ken Burns 2.5D. Пропсы (words/скрин/цвета) отдаёт наш пайплайн.
