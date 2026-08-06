# Стек Reels-фабрики — из лучших открытых проектов

Собрано из топовых по рейтингу опенсорс-репозиториев по «контент-заводу»: из каждого
взято самое мощное и встроено в движок. Ниже — что откуда и чем реализовано.

## Откуда что взято

| Возможность | Источник (репозиторий/подход) | Реализация в фабрике |
|---|---|---|
| Авто-динамика: рез пауз/тишины, темп | **auto-editor** (~8K⭐) | `dynamic_cut.py` |
| Пословные субтитры с подсветкой | **Captacity** + **WhisperX** подход | `transcribe.py` (faster-whisper) + `render.py` captions |
| Логика авто-выбора моментов, 9:16 | **Shorts Maker** (OpusClip-опенсорс, 4.5K⭐) | `auto_edl.py` |
| Стоковые видео в тему | **Pexels API** (как в **MoneyPrinterTurbo** 72K⭐) | `stock.py` |
| Нарезка в бит музыки | **librosa** | `beat_sync.py` |
| Переходы (динамика) | ffmpeg **xfade** / подход **gl-transitions·editly** | `render.py` concat |
| Зум камеры, Ken Burns, панч | ffmpeg **zoompan** | `render.py` motion |
| Перемотка туда-сюда (бумеранг) | ffmpeg **reverse/concat** | `render.py` motion |
| Громкость под соцсети, цветовой панч | ffmpeg **loudnorm (EBU R128)** + eq/unsharp | `render.py` finalize |
| Оценка удержания/виральности | своя методика + **Higgsfield virality_predictor** | `reels.json` + `viral_kit.py` |

Не взяли (не под твой кейс): **MoneyPrinterTurbo/ShortGPT** генерят видео со стоков
с нуля — твоего лица/голоса там не будет. Мы монтируем ТВОЁ сырьё.

## Виральный арсенал (модули)

- `dynamic_cut.py` — auto-editor: убрать мёртвый воздух, держать темп.
- `transcribe.py` — faster-whisper: речь → слова с таймингами.
- `render.py` — склейка, рефрейминг 9:16, зум/панч/Ken Burns/бумеранг, пословные
  анимированные субтитры, переходы xfade, музыка, финал (loudnorm + цвет).
- `auto_edl.py` — авто-план из папки: хук, нарезка, движение, субтитры.
- `beat_sync.py` — биты музыки (librosa) для нарезки в ритм.
- `stock.py` — Pexels: b-roll в тему по ключевым словам речи.
- `viral_kit.py` — **реестр инструментов + авто-подбор**: ИИ по сигналам ролика
  выбирает, что включить для роста виральности (каталог → `viral.json`).

## Как ИИ подбирает инструменты под виральность

`viral_kit.recommend(signals)` смотрит на ролик (есть речь? музыка? ключевые слова?
длина, доля статики) и включает нужные техники с обоснованием. Пример:

```
python3 montage/viral_kit.py --edl plan.json
  [10] Хук 0–3 с              — база залетаемости
  [ 9] Авто-динамика          — убрать мёртвый воздух
  [ 9] Пословные субтитры     — ≈80% смотрят без звука
  [ 8] Нарезка в бит          — склейки в бит держат внимание
  [ 7] B-roll / сток в тему   — иллюстрируем смысл
  ...
```

## Установка про-арсенала

```bash
pip install -r montage/requirements.txt          # база (ffmpeg, Pillow, heif)
pip install -r montage/requirements-subs.txt      # субтитры (faster-whisper)
pip install -r montage/requirements-pro.txt       # auto-editor, librosa
export PEXELS_API_KEY=...                          # опц.: стоковые видео
```

Сервер/Cloudflare-образы ставят это автоматически (см. `server/`, `cloudflare/`).
