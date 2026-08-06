# studio/ — наш «Цех» по образцу Talgat AI Video Studio

Программный монтаж без видеоредакторов: код собирает видео. Ниже — что уже
установлено и работает у нас, и что требует твоих API-ключей.

## Статус компонентов

### ✅ Установлено и работает (опенсорс, без ключей)
| Компонент | Роль | Где |
|---|---|---|
| ffmpeg (статик) | нарезка, concat, loudnorm, эффекты | `montage/` |
| **Автофрейминг по лицам (OpenCV YuNet)** | кадрирование 9:16 по лицу | `studio/engine/autoframe.py` + `yunet.onnx` |
| Пословные субтитры (faster-whisper) | караоке-сабы | `montage/transcribe.py` |
| auto-editor | рез пауз/тишины, динамика | `montage/dynamic_cut.py` |
| Биты музыки (librosa) | нарезка в ритм | `montage/beat_sync.py` |
| Сток b-roll (Pexels) | кадры в тему | `montage/stock.py` |
| Зум/панч/Ken Burns/бумеранг/переходы | движение | `montage/render.py` |
| Громкость −14 LUFS + цвет + progress bar | финал | `montage/render.py` |
| Реестр виральных инструментов | авто-подбор | `montage/viral_kit.py` |
| Канон вкуса + ревью-чеклист | качество | `studio/guides/MONTAGE-TASTE.md` |

### ⏳ Ставится следующей фазой (опенсорс, тяжёлое)
- **Remotion 4 (React)** — рендер-ядро для кинетика/караоке-сцен (`template/`, `engine/*.tsx`). Node есть.
- **rembg** — вырезка фона (`pipeline/matte.py`).
- **MiDaS depth** — 2.5D-параллакс Ken Burns (`pipeline/depth_map.py`).
- **SFX-набор** — звуки на склейки (нужны нормализованные ассеты).

### 🔑 Требует ТВОИХ ключей (внешние платные API)
| Сервис | Роль | Ключ |
|---|---|---|
| ElevenLabs | Scribe-транскрипт, TTS, **клон-голоса**, музыка | `ELEVEN_KEY` |
| kie.ai | видеогенерация: Kling/Seedance/Veo/Wan/Grok | `KIE_KEY` |
| OpenRouter | fallback видеомоделей | `OPENROUTER_API_KEY` |
| xAI | Grok Imagine (оживление фото) | `XAI_API_KEY` |

Ключи → `studio/.env` (`chmod 600`), проверка: `python3 studio/pipeline/check_keys.py`.
Значения ключей в чат/код/гит не попадают.

## Структура (по образцу кита Talgat)

```
studio/
  engine/     autoframe.py + yunet.onnx (детект лиц)   [+ *.tsx движки — фаза 2]
  pipeline/   check_keys.py                              [+ depth_map, matte, sfx — фаза 2]
  guides/     MONTAGE-TASTE.md (канон вкуса)             [+ VIDEO-MODELS, ENGINE — фаза 2]
  .env.example
  README.md
```

## Быстрый старт
```bash
pip install -r studio/requirements.txt          # opencv, onnxruntime (автофрейминг)
python3 studio/engine/autoframe.py clip.mp4 out.mp4    # кадрировать по лицу
python3 studio/pipeline/check_keys.py                  # какие ключи заданы
```

## Честно про рамки
Полная студия Talgat — это ещё Remotion-движки (`*.tsx`), 34 шрифта с казахскими
глифами, 44 SFX и клиентские гайды. Открытую инфраструктуру ставлю по фазам;
генеративные части (видео/голос/музыка) работают только с твоими ключами —
их я подключу кодом, но ключи заводишь ты.
