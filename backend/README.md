# Панель управления видео-конвейером — бэкенд

Труба: **Telegram** (ввод/вывод) → **Панель** (оркестрация по коду) → **один видео-инструмент** → мастер обратно в Telegram.

Принципы: никакого NLP (команда = имя пресета), один инструмент за раз, панель правит рецепт (пресеты), бот тупой, сценарий воркера зашит в код. Сменная деталь одна — `app/adapters/<tool>.py`.

## Структура

```
app/
  main.py            FastAPI: /webhook/telegram, /webhook/tool, /api/jobs, /api/presets
  config.py          env-настройки (все секреты только тут)
  db.py  models.py   Postgres + SQLAlchemy (таблицы presets, jobs)
  schemas.py         Pydantic-схемы API
  storage.py         R2 (boto3) с локальным фолбэком
  telegram_api.py    труба ввода/вывода (скачать сырьё / отправить мастер)
  ffmpeg_assemble.py FFmpeg-сборка мастера + превью по пресету
  adapters/          контракт submit()/parse_callback() + stub (# REPLACE PER TOOL)
  worker/            фиксированный сценарий (pipeline.py) + цикл (runner.py)
migrations/          Alembic
seed.py              сид тестового пресета «reels»
```

## Машина статусов job

```
accepted ──▶ processing[downloading] ──▶ processing[rendering] ──(callback инструмента)──▶
             processing[assembling] ──▶ processing[delivering] ──▶ done
любой шаг ─(ошибка)─▶ error     |     cancel ─▶ canceled     |     retry ─▶ accepted (заново с шага 1)
```

Строка `jobs` = один ролик = цепочка статусов. Отдельной таблицы логов нет.
`settings_snapshot` замораживает пресет в момент создания job — правка пресета не ломает историю.

**Поля сверх ТЗ** (инженерная необходимость async-стыковки шагов 3→4):
`source_stored_url` — сырьё, залитое в R2; `tool_output_url` — выход инструмента до FFmpeg-сборки.

## Локальный запуск

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # при желании впишите креды; без них работает фолбэк

alembic upgrade head            # миграции
python seed.py                  # тестовый пресет «reels»

uvicorn app.main:app --reload   # API :8000
python -m app.worker.runner     # воркер (отдельный терминал)
```

Без `TELEGRAM_BOT_TOKEN` и R2-кредов панель работает в dev-режиме: сырьё генерируется
ffmpeg-ом (`DEV_FAKE_SOURCE`), файлы пишутся на диск (`LOCAL_STORAGE_DIR`), а `TOOL=stub`
сам эмулирует async-callback инструмента — так весь конвейер проходит зелёным на пустышке.

## Прогон конвейера (smoke)

```bash
python -m app.smoke   # создаёт job через /webhook/telegram и ждёт статус done
```

## Деплой (Railway)

Два процесса из `Procfile`: `web` (миграции + uvicorn) и `worker`. Env — из раздела 7 ТЗ.
Telegram webhook: `setWebhook` на `${PANEL_BASE_URL}/webhook/telegram`.

## Подключение реального инструмента (шаг 7)

1. Создать `app/adapters/<tool>.py` c `submit()` и `parse_callback()` (см. `stub.py`).
2. Зарегистрировать в `app/adapters/__init__.py._REGISTRY`.
3. Выставить `TOOL=<tool>` и `TOOL_API_KEY`. Остальной код не меняется.
